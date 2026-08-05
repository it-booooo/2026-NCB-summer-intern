# Full-resolution filtered analysis cache

Power-spectrum and spectrogram requests need the complete, full-resolution LFP
range. The navigation waveform cannot be reused because it is downsampled, and
the playback cache contains only bounded local segments.

For filtered requests, `LfpDataset.analysis_values_file()` stores the prepared
values in the existing signal-cache root. The cache identity includes:

- source path, size, and modification time;
- channel and exact source sample-index range;
- sample rate and every filter setting;
- a filter-cache algorithm version.

The first request filters in 250,000-sample blocks into a disk-backed memmap.
Later power-spectrum, spectrogram, and image-export requests with the same
identity lease the same file without filtering again. Raw requests and filtered
entries larger than the configured budget continue to use delete-on-close
temporary files.

## Resource limits

- The filtered-analysis category is limited to 5 GiB by default.
- The existing combined signal-cache limit remains 20 GiB.
- Entries use LRU access timestamps and expire through the existing 30-day
  cleanup policy.
- Active files are protected from cleanup until their worker finishes.
- Builds use temporary directories plus atomic publication; cancellation removes
  partial files.
- Full-resolution values remain disk-backed. Filtering still processes bounded
  blocks, and the renderer no longer copies an all-finite memmap into another
  full-size RAM array.

Set `PIG_LFP_ANALYSIS_CACHE_MAX_BYTES` to a non-negative byte count to change the
filtered-analysis budget. Set it to `0` to disable persistent filtered-analysis
caching. A single result that cannot fit within the budget is processed using a
temporary file and is deleted after rendering.
