#!/usr/bin/env python3
import os
import sys
import subprocess
import urllib.request
import tarfile
import shutil
import tempfile
import argparse
import time
import hashlib
from pathlib import Path
from urllib.parse import urlparse


def log_progress(message, start_time=None):
    """Log progress with timestamp and elapsed time"""
    timestamp = time.strftime("%H:%M:%S")
    if start_time:
        elapsed = time.time() - start_time
        print(f"[{timestamp}] {message} (elapsed: {elapsed:.1f}s)")
    else:
        print(f"[{timestamp}] {message}")


def download_file_with_progress(url, dest_path):
    """Download file from URL with progress indication"""
    start_time = time.time()
    log_progress(f"📥 Starting download: {url}")

    def progress_hook(block_num, block_size, total_size):
        if total_size > 0:
            percent = min(100.0, (block_num * block_size) / total_size * 100)
            if (
                block_num % 50 == 0 or percent >= 100
            ):  # Update every ~50 blocks or at completion
                print(
                    f"    Progress: {percent:.1f}% ({block_num * block_size // 1024 // 1024}MB)",
                    end="\r",
                )

    urllib.request.urlretrieve(url, dest_path, progress_hook)
    print()  # New line after progress
    log_progress(f"✅ Download completed: {dest_path}", start_time)


def get_cache_path(url):
    """Get cache file path based on URL hash"""
    cache_dir = Path.home() / ".cache" / "ghostscript_build"
    cache_dir.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.sha256(url.encode()).hexdigest()[:12]
    filename = Path(urlparse(url).path).name
    return cache_dir / f"{url_hash}_{filename}"


def extract_tarball_with_progress(tar_path, extract_to):
    """Extract tarball to specified directory with progress tracking"""
    start_time = time.time()
    log_progress(f"📂 Starting extraction: {tar_path}")

    with tarfile.open(tar_path, "r:gz") as tar:
        members = tar.getmembers()
        total_files = len(members)

        for i, member in enumerate(members):
            tar.extract(member, extract_to)
            if i % 100 == 0 or i == total_files - 1:  # Update every 100 files
                percent = (i + 1) / total_files * 100
                print(
                    f"    Extracting: {percent:.1f}% ({i + 1}/{total_files} files)",
                    end="\r",
                )

        print()  # New line after progress
    log_progress("✅ Extraction completed", start_time)


def get_optimal_ram_disk_size():
    """Determine optimal RAM disk size for GitHub Mac runners"""
    # GitHub Actions Mac runners have 14GB RAM
    # Use 3GB for optimal performance without overwhelming the system
    if os.environ.get("GITHUB_ACTIONS") == "true":
        return 3072  # 3GB for GitHub Actions Mac runners
    else:
        return 2048  # 2GB for local development


def setup_ram_disk(size_mb=None):
    """Set up RAM disk for faster compilation (macOS/Linux)"""
    if size_mb is None:
        size_mb = get_optimal_ram_disk_size()

    try:
        if sys.platform == "darwin":  # macOS
            # Create RAM disk
            sectors = size_mb * 2048  # 512-byte sectors
            result = subprocess.run(
                ["hdiutil", "attach", "-nomount", f"ram://{sectors}"],
                capture_output=True,
                text=True,
                check=True,
            )
            device = result.stdout.strip()

            # Format as HFS+
            subprocess.run(["newfs_hfs", device], capture_output=True, check=True)

            # Create mount point and mount
            ram_disk_path = Path("/tmp/gs_ramdisk")
            ram_disk_path.mkdir(exist_ok=True)
            subprocess.run(
                ["mount", "-t", "hfs", device, str(ram_disk_path)], check=True
            )

            log_progress(f"💾 RAM disk created: {ram_disk_path} ({size_mb}MB)")
            return ram_disk_path, device

    except Exception as e:
        log_progress(f"⚠️  RAM disk setup failed, using regular disk: {e}")
        return None, None


def cleanup_ram_disk(ram_disk_path, device):
    """Clean up RAM disk"""
    if ram_disk_path and device:
        try:
            subprocess.run(["umount", str(ram_disk_path)], check=False)
            subprocess.run(["hdiutil", "detach", device], check=False)
            log_progress("💾 RAM disk cleaned up")
        except Exception as e:
            log_progress(f"⚠️  RAM disk cleanup failed: {e}")


def run_command_with_progress(cmd, cwd=None, check=True, description=None):
    """Run shell command with progress tracking and better error handling"""
    start_time = time.time()
    cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
    desc = description or f"Running: {cmd_str}"
    log_progress(f"🔄 {desc}")

    try:
        # For long-running commands like make, show periodic updates
        if isinstance(cmd, list) and cmd[0] == "make":
            process = subprocess.Popen(
                cmd,
                shell=False,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
            )

            output_lines = []
            while True:
                if process.stdout is None:
                    break
                output = process.stdout.readline()
                if output == "" and process.poll() is not None:
                    break
                if output:
                    output_lines.append(output.strip())
                    # Show progress every 10 seconds or on certain keywords
                    elapsed = time.time() - start_time
                    if (len(output_lines) % 20 == 0 and elapsed > 10) or any(
                        keyword in output.lower()
                        for keyword in ["compiling", "linking", "building"]
                    ):
                        print(
                            f"    Build progress: {elapsed:.0f}s elapsed, {len(output_lines)} operations completed"
                        )

            result_code = process.poll()
            if result_code is None:
                result_code = 0
            if result_code != 0 and check:
                raise subprocess.CalledProcessError(
                    result_code, cmd, "\n".join(output_lines[-20:])
                )

            log_progress(f"✅ {desc}", start_time)
            return type(
                "Result",
                (),
                {"returncode": result_code, "stdout": "\n".join(output_lines)},
            )()
        else:
            result = subprocess.run(
                cmd,
                shell=isinstance(cmd, str),
                cwd=cwd,
                check=check,
                capture_output=True,
                text=True,
            )
            log_progress(f"✅ {desc}", start_time)
            return result

    except subprocess.CalledProcessError as e:
        log_progress(f"❌ Command failed: {cmd_str}")
        if e.stderr:
            print(f"Error output: {e.stderr}")
        if check:
            raise
        return e


def check_dependencies():
    """Check if required build tools are available with progress tracking"""
    log_progress("🔍 Checking build dependencies")
    required_tools = ["gcc", "make", "autoconf"]
    missing = []

    for tool in required_tools:
        try:
            subprocess.run(["which", tool], check=True, capture_output=True)
            print(f"    ✅ {tool} found")
        except subprocess.CalledProcessError:
            missing.append(tool)
            print(f"    ❌ {tool} missing")

    if missing:
        log_progress(f"❌ Missing required tools: {', '.join(missing)}")
        print("Please install build essentials:")
        print("  macOS: xcode-select --install")
        print("  Ubuntu: sudo apt-get install build-essential autoconf")
        sys.exit(1)
    else:
        log_progress("✅ All dependencies satisfied")


def build_ghostscript(cleanup=True, use_ram_disk=True):
    """Main function to download and build Ghostscript with performance optimizations"""
    gs_url = "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10051/ghostscript-10.05.1.tar.gz"
    total_start_time = time.time()

    log_progress("🚀 Starting Ghostscript build process")

    # Check dependencies first
    check_dependencies()

    # Set up RAM disk for faster compilation if requested
    ram_disk_path, ram_device = None, None
    if use_ram_disk:
        ram_disk_path, ram_device = (
            setup_ram_disk()
        )  # Dynamic RAM disk size based on system

    # Determine work directory (RAM disk or temp)
    work_base = ram_disk_path if ram_disk_path else Path(tempfile.gettempdir())

    # Create build directory
    build_dir = Path("./build")
    build_dir.mkdir(exist_ok=True)
    log_progress(f"📁 Build directory: {build_dir.absolute()}")

    # Create output directory for final binary
    output_dir = Path("./bin")
    output_dir.mkdir(exist_ok=True)
    log_progress(f"📁 Output directory: {output_dir.absolute()}")

    try:
        with tempfile.TemporaryDirectory(dir=work_base) as temp_dir:
            temp_path = Path(temp_dir)
            log_progress(
                f"📁 Working in: {temp_path} {'(RAM disk)' if ram_disk_path else '(regular disk)'}"
            )

            # Check cache first to avoid re-downloading
            cache_path = get_cache_path(gs_url)
            tar_path = temp_path / "ghostscript-10.05.1.tar.gz"

            if cache_path.exists():
                log_progress(f"📦 Using cached file: {cache_path}")
                shutil.copy2(cache_path, tar_path)
            else:
                log_progress("📦 No cache found, downloading fresh")
                # Download Ghostscript source
                download_file_with_progress(gs_url, tar_path)
                # Cache the downloaded file
                shutil.copy2(tar_path, cache_path)
                log_progress(f"💾 Cached for future builds: {cache_path}")

            # Extract source with progress
            extract_tarball_with_progress(tar_path, temp_path)

            # Find extracted directory
            gs_source_dir = None
            log_progress("🔍 Locating source directory")
            for item in temp_path.iterdir():
                if item.is_dir() and item.name.startswith("ghostscript"):
                    gs_source_dir = item
                    break

            if not gs_source_dir:
                raise RuntimeError("Could not find extracted Ghostscript directory")

            log_progress(f"📂 Found source directory: {gs_source_dir.name}")

            # Try different configure approaches with optimizations
            configure_attempts = [
                # Optimized configuration first - disable unnecessary features for speed
                [
                    "./configure",
                    f"--prefix={build_dir.absolute()}",
                    "--disable-cups",
                    "--without-x",
                    "--disable-gtk",
                    "--without-libtiff",
                    "--without-libpng",
                    "--disable-fontconfig",
                    "--disable-dbus",
                    "CFLAGS=-O3 -march=native -pipe",
                    "CXXFLAGS=-O3 -march=native -pipe",
                ],
                # Fallback minimal configuration
                ["./configure", f"--prefix={build_dir.absolute()}"],
            ]

            configure_success = False
            for i, configure_cmd in enumerate(configure_attempts):
                result = run_command_with_progress(
                    configure_cmd,
                    cwd=gs_source_dir,
                    check=False,
                    description=f"Configuring build (attempt {i + 1}/{len(configure_attempts)})",
                )
                if result.returncode == 0:
                    configure_success = True
                    log_progress(f"✅ Configuration successful on attempt {i + 1}")
                    break
                else:
                    log_progress(f"⚠️  Configure attempt {i + 1} failed, trying next...")

            if not configure_success:
                raise RuntimeError("All configure attempts failed")

            # Build with optimized parallelism - use more jobs but with memory management
            cpu_count = os.cpu_count() or 4
            make_jobs = min(
                cpu_count + 2, 12
            )  # Cap at 12 to avoid overwhelming the system

            # Don't override CFLAGS in make - they're already set in configure
            make_cmd = ["make", f"-j{make_jobs}"]

            run_command_with_progress(
                make_cmd,
                cwd=gs_source_dir,
                description=f"Building Ghostscript ({make_jobs} parallel jobs)",
            )

            # Install to build directory
            run_command_with_progress(
                ["make", "install"],
                cwd=gs_source_dir,
                description="Installing to build directory",
            )

            # Copy the main binary to output directory
            gs_binary = build_dir / "bin" / "gs"
            if gs_binary.exists():
                final_binary = output_dir / "ghostscript"
                log_progress("📋 Copying final binary to output directory")
                shutil.copy2(gs_binary, final_binary)

                # Make executable
                os.chmod(final_binary, 0o755)

                log_progress(
                    f"🎉 Standalone Ghostscript binary created: {final_binary.absolute()}"
                )

                # Test the binary
                log_progress("🧪 Testing binary functionality")
                result = run_command_with_progress(
                    [str(final_binary), "--version"],
                    check=False,
                    description="Testing binary version",
                )
                if result.returncode == 0:
                    log_progress("✅ Binary test successful!")

                    # Clean up build artifacts if requested
                    if cleanup:
                        log_progress("🧹 Cleaning up build artifacts")
                        if build_dir.exists():
                            shutil.rmtree(build_dir)
                            log_progress(f"🗑️  Removed build directory: {build_dir}")

                        # Clean up any test files
                        test_files = [
                            "test.ps",
                            "test_original.pdf",
                            "test_prepress.pdf",
                            "test_printer.pdf",
                            "test_ebook.pdf",
                            "test_screen.pdf",
                            "test_max_compression.pdf",
                            "test_info.pdf",
                        ]

                        cleaned_files = []
                        for test_file in test_files:
                            test_path = Path(test_file)
                            if test_path.exists():
                                test_path.unlink()
                                cleaned_files.append(test_file)

                        if cleaned_files:
                            log_progress(
                                f"🗑️  Removed test files: {', '.join(cleaned_files)}"
                            )

                        log_progress("✅ Cleanup completed!")
                    else:
                        log_progress(
                            "📁 Build artifacts retained (use --cleanup to remove)"
                        )

                else:
                    log_progress("❌ Binary test failed")

            else:
                raise RuntimeError("Ghostscript binary not found after build")

    finally:
        # Clean up RAM disk
        if ram_disk_path and ram_device:
            cleanup_ram_disk(ram_disk_path, ram_device)

    # Final summary
    total_elapsed = time.time() - total_start_time
    log_progress(f"🏁 Build process completed in {total_elapsed:.1f} seconds")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build standalone Ghostscript binary with performance optimizations"
    )
    parser.add_argument(
        "--no-cleanup",
        action="store_true",
        help="Keep build artifacts after successful build",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        default=True,
        help="Clean up build artifacts after successful build (default)",
    )
    parser.add_argument(
        "--no-ram-disk",
        action="store_true",
        help="Disable RAM disk optimization (compile on regular disk)",
    )

    args = parser.parse_args()

    # Determine cleanup behavior
    cleanup = not args.no_cleanup
    use_ram_disk = not args.no_ram_disk

    try:
        build_ghostscript(cleanup=cleanup, use_ram_disk=use_ram_disk)
        log_progress("🎉 Build completed successfully!")
    except Exception as e:
        log_progress(f"💥 Build failed: {e}")
        sys.exit(1)
