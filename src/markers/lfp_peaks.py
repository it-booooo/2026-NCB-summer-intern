from .models import (
    Marker,
    MarkerKind,
    MarkerSource,
    RecordPosition,
)


def peak_records_to_markers(channel, records):
    """Convert pure worker records to record-domain LFP peak markers."""

    channel = int(channel)
    return [
        Marker(
            kind=MarkerKind.LFP_PEAK,
            source=MarkerSource.LFP_DETECTION,
            position=RecordPosition(record["record_time_s"]),
            note=(
                f"channel={channel}, value={record['value']:.6g}, "
                f"{'negative' if record['negative'] else 'positive'} peak"
            ),
            payload={"channel": channel, "value": record["value"]},
        )
        for record in records
    ]
