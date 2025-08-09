# Ghostscript Standalone Binary Builder

This script downloads and compiles Ghostscript 10.05.1 into a standalone binary that can be bundled with other applications.

## Usage

Run the build script:

```bash
python3 build_ghostscript.py
```

**Options:**
- `--no-cleanup`: Keep build artifacts after successful build
- `--cleanup`: Clean up build artifacts (default behavior)

The script will:
1. Download Ghostscript source from GitHub releases
2. Configure it for static compilation (no external dependencies)
3. Compile into a standalone binary
4. Place the final binary in `./bin/ghostscript`
5. Clean up build artifacts and temporary files (unless `--no-cleanup` is used)

## Requirements

- Python 3.6+
- GCC or compatible C compiler
- Make
- Standard development tools (autoconf, etc.)

On macOS:
```bash
xcode-select --install
```

On Ubuntu/Debian:
```bash
sudo apt-get install build-essential autoconf
```

## Output

The standalone binary will be created at `./bin/ghostscript` and can be distributed independently without requiring Ghostscript to be installed on the target system.