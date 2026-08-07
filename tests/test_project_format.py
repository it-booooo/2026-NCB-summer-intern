import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

from src.app_state import AppState
from src.data_import.project_load_worker import prepare_project_objects
from src.lfp_settings import LfpFilterSettings
from src.led_detection import LedBrightnessPoint
from src.markers import (
    Marker,
    MarkerKind,
    MarkerSource,
    RecordPosition,
    VideoPosition,
    marker_to_dict,
)
from src.project_archive import load_project_archive
from src.project_format import PROJECT_FORMAT, PROJECT_VERSION
from src.project_format import (
    deserialize_lfp_filter_settings,
    serialize_lfp_filter_settings,
    validate_manifest,
    validate_project_json_sizes,
    validate_state,
    validate_video_bounds,
)


class AnalysisSettingsTests(unittest.TestCase):
    def test_project_format_uses_three_axis_source_and_setting_names(self):
        source = {
            "external_path": "three_axis.csv",
            "filename": "three_axis.csv",
            "fingerprint": {"size": 0, "sample_sha256": "0" * 64},
        }
        manifest = {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "sources": {"three_axis": source},
        }
        state = {"data": {"three_axis_step": 4}}

        self.assertEqual(validate_manifest(manifest), {"three_axis": source})
        self.assertIs(validate_state(state), state)

    def test_project_format_rejects_old_axis_source_name(self):
        manifest = {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "sources": {"axis": {}},
        }

        with self.assertRaisesRegex(ValueError, "Unsupported project source type"):
            validate_manifest(manifest)

    def test_peak_settings_live_in_application_state(self):
        state = AppState()

        self.assertEqual(state.analysis.lfp_peak_height_sigma, 8.0)
        self.assertEqual(state.analysis.lfp_peak_prominence_sigma, 6.0)
        self.assertEqual(state.analysis.lfp_peak_min_distance_sec, 1.0)

    def test_project_validation_accepts_valid_analysis_settings(self):
        state = {
            "analysis": {
                "lfp_peak_height_sigma": 7.5,
                "lfp_peak_prominence_sigma": 5.5,
                "lfp_peak_min_distance_sec": 0.02,
            }
        }

        self.assertIs(validate_state(state), state)

    def test_project_validation_accepts_valid_led_cache(self):
        point = {"frame_index": 10, "video_time_sec": 0.5, "brightness": 0.8}
        state = {
            "led": {
                "analysis_points": [dict(point)],
                "brightness_cache": [
                    {
                        "roi": [1, 2, 30, 40],
                        "rotation_degrees": 180,
                        "fps": 30.0,
                        "start_frame": 0,
                        "end_frame": 100,
                        "coarse_step": 20,
                        "points": [dict(point)],
                    }
                ],
            }
        }

        self.assertIs(validate_state(state), state)

    def test_project_validation_rejects_malformed_led_cache_point(self):
        state = {
            "led": {
                "brightness_cache": [
                    {"points": [{"frame_index": 1, "brightness": 0.8}]}
                ]
            }
        }

        with self.assertRaisesRegex(ValueError, "entry is invalid"):
            validate_state(state)

    def test_project_validation_rejects_invalid_led_cache_range(self):
        state = {
            "led": {
                "brightness_cache": [
                    {"start_frame": 20, "end_frame": 10, "points": []}
                ]
            }
        }

        with self.assertRaisesRegex(ValueError, "frame range"):
            validate_state(state)

    def test_serialized_project_must_fit_loader_limits(self):
        with patch("src.project_format.MAX_STATE_BYTES", 3):
            with self.assertRaisesRegex(ValueError, "state.json is too large"):
                validate_project_json_sizes(b"{}", b"1234")

    def test_compact_json_preserves_project_state(self):
        state = {
            "markers": [
                {
                    "marker_id": "marker-1",
                    "kind": "led_on",
                    "source": "led_detection",
                    "position": {
                        "domain": "video",
                        "time_sec": 1.25,
                        "frame_index": 30,
                    },
                    "note": "",
                    "payload": {},
                }
            ]
        }

        pretty = json.dumps(state, indent=2, ensure_ascii=False).encode("utf-8")
        compact = json.dumps(
            state, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

        self.assertEqual(json.loads(compact), state)
        self.assertLess(len(compact), len(pretty))

    def test_project_validation_rejects_invalid_minimum_distance(self):
        with self.assertRaises(ValueError):
            validate_state(
                {"analysis": {"lfp_peak_min_distance_sec": 0.0}}
            )

    def test_project_validation_accepts_negative_marker_times(self):
        markers = [
            Marker(
                kind=MarkerKind.TTL,
                source=MarkerSource.TTL_IMPORT,
                position=RecordPosition(-1.25),
            ),
            Marker(
                kind=MarkerKind.LED_ON,
                source=MarkerSource.LED_DETECTION,
                position=VideoPosition(time_sec=-0.5, frame_index=0),
            ),
        ]
        state = {"markers": [marker_to_dict(marker) for marker in markers]}

        self.assertIs(validate_state(state), state)


class ProjectArchiveTests(unittest.TestCase):
    def test_default_lfp_filter_settings_are_json_round_trip_safe(self):
        settings = LfpFilterSettings()

        payload = serialize_lfp_filter_settings(settings)

        validated = validate_state({"data": {"lfp_filter_settings": payload}})

        self.assertIs(validated["data"]["lfp_filter_settings"], payload)
        self.assertEqual(deserialize_lfp_filter_settings(payload), settings)

    def test_lfp_filter_settings_json_round_trip(self):
        settings = LfpFilterSettings(
            show_filtered=True,
            bandpass_enabled=True,
            bandpass_low_hz=5.0,
            bandpass_high_hz=80.0,
            line_noise_hz=50.0,
            line_noise_frequencies_hz=(50.0, 100.0),
            line_noise_method="regression",
            regression_all_harmonics=True,
        )

        payload = serialize_lfp_filter_settings(settings)
        encoded = json.dumps(payload)
        restored = deserialize_lfp_filter_settings(json.loads(encoded))

        self.assertIsInstance(payload, dict)
        self.assertEqual(payload["line_noise_frequencies_hz"], [50.0, 100.0])
        self.assertEqual(restored, settings)

    def test_project_archive_round_trip_prepares_lfp_settings_object(self):
        settings = LfpFilterSettings(
            show_filtered=True,
            line_noise_method="regression",
            line_noise_hz=60.0,
            line_noise_frequencies_hz=(60.0, 120.0),
            regression_all_harmonics=True,
        )
        manifest = {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "sources": {},
        }
        state = {
            "data": {
                "lfp_filter_settings": serialize_lfp_filter_settings(settings)
            }
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.pigproj"
            with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("state.json", json.dumps(state))

            loaded = prepare_project_objects(load_project_archive(path))

        self.assertEqual(
            loaded["state"]["data"]["lfp_filter_settings"],
            settings,
        )

    def test_legacy_project_lfp_dictionary_and_scalar_are_migrated(self):
        legacy = {
            "data": {
                "line_noise_hz": 50.0,
                "lfp_filter_settings": {
                    "show_filtered": True,
                    "line_noise_method": "regression",
                    "regression_harmonics": 2,
                },
            }
        }
        manifest = {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "sources": {},
        }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.pigproj"
            with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("state.json", json.dumps(legacy))

            loaded = prepare_project_objects(load_project_archive(path))

        migrated_data = loaded["state"]["data"]
        settings = migrated_data["lfp_filter_settings"]

        self.assertNotIn("line_noise_hz", migrated_data)
        self.assertEqual(settings.line_noise_hz, 50.0)
        self.assertEqual(settings.line_noise_frequencies_hz, (50.0,))
        self.assertTrue(settings.regression_all_harmonics)

    def test_project_archive_is_read_and_validated_without_qt(self):
        manifest = {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "sources": {},
        }
        state = {"analysis": {"lfp_peak_min_distance_sec": 0.5}}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.pigproj"
            with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("state.json", json.dumps(state))

            loaded = load_project_archive(path)

        self.assertEqual(loaded["sources"], {})
        self.assertEqual(loaded["state"], state)

    def test_project_archive_rejects_invalid_state_before_restore(self):
        manifest = {
            "format": PROJECT_FORMAT,
            "version": PROJECT_VERSION,
            "sources": {},
        }
        state = {"analysis": {"lfp_peak_min_distance_sec": 0.0}}

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.pigproj"
            with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("state.json", json.dumps(state))

            with self.assertRaises(ValueError):
                load_project_archive(path)

    def test_project_runtime_objects_are_prepared_once(self):
        marker = Marker(
            kind=MarkerKind.TTL,
            source=MarkerSource.TTL_IMPORT,
            position=RecordPosition(1.25),
        )
        point = {
            "frame_index": 10,
            "video_time_sec": 0.5,
            "brightness": 42.0,
        }
        archive_data = {
            "state": {
                "markers": [marker_to_dict(marker)],
                "led": {
                    "analysis_points": [dict(point)],
                    "brightness_cache": [{"points": [dict(point)]}],
                },
            }
        }

        prepared = prepare_project_objects(archive_data)
        prepared_again = prepare_project_objects(prepared)

        self.assertIs(prepared_again, prepared)
        self.assertEqual(prepared["state"]["markers"], [marker])
        self.assertIsInstance(
            prepared["state"]["led"]["analysis_points"][0],
            LedBrightnessPoint,
        )
        self.assertIsInstance(
            prepared["state"]["led"]["brightness_cache"][0]["points"][0],
            LedBrightnessPoint,
        )

    def test_video_bounds_accept_prepared_marker_objects(self):
        marker = Marker(
            kind=MarkerKind.LED_ON,
            source=MarkerSource.LED_DETECTION,
            position=VideoPosition(time_sec=-0.5, frame_index=10),
        )
        state = {"video": {"current_frame": 0}, "markers": [marker]}
        metadata = SimpleNamespace(
            total_frames=100,
            duration_sec=5.0,
            width=640,
            height=480,
        )

        validate_video_bounds(state, metadata)


if __name__ == "__main__":
    unittest.main()
