#!/usr/bin/env python3
import os
import sys
import subprocess
import urllib.request
import tarfile
import shutil
import tempfile
import argparse
from pathlib import Path

def download_file(url, dest_path):
    """Download file from URL to destination path"""
    print(f"Downloading {url}...")
    urllib.request.urlretrieve(url, dest_path)
    print(f"Downloaded to {dest_path}")

def extract_tarball(tar_path, extract_to):
    """Extract tarball to specified directory"""
    print(f"Extracting {tar_path}...")
    with tarfile.open(tar_path, 'r:gz') as tar:
        tar.extractall(extract_to)
    print("Extraction complete")

def run_command(cmd, cwd=None, check=True):
    """Run shell command and handle errors"""
    print(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    try:
        result = subprocess.run(cmd, shell=isinstance(cmd, str), cwd=cwd, 
                              check=check, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout)
        return result
    except subprocess.CalledProcessError as e:
        print(f"Command failed: {e}")
        if e.stderr:
            print(f"Error output: {e.stderr}")
        if check:
            raise
        return e

def check_dependencies():
    """Check if required build tools are available"""
    required_tools = ['gcc', 'make', 'autoconf']
    missing = []
    
    for tool in required_tools:
        try:
            run_command(['which', tool], check=True)
        except subprocess.CalledProcessError:
            missing.append(tool)
    
    if missing:
        print(f"Missing required tools: {', '.join(missing)}")
        print("Please install build essentials:")
        print("  macOS: xcode-select --install")
        print("  Ubuntu: sudo apt-get install build-essential autoconf")
        sys.exit(1)

def build_ghostscript(cleanup=True):
    """Main function to download and build Ghostscript"""
    gs_url = "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10051/ghostscript-10.05.1.tar.gz"
    
    # Check dependencies first
    check_dependencies()
    
    # Create build directory
    build_dir = Path("./build")
    build_dir.mkdir(exist_ok=True)
    
    # Create output directory for final binary
    output_dir = Path("./bin")
    output_dir.mkdir(exist_ok=True)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        
        # Download Ghostscript source
        tar_path = temp_path / "ghostscript-10.05.1.tar.gz"
        download_file(gs_url, tar_path)
        
        # Extract source
        extract_tarball(tar_path, temp_path)
        
        # Find extracted directory
        gs_source_dir = None
        for item in temp_path.iterdir():
            if item.is_dir() and item.name.startswith("ghostscript"):
                gs_source_dir = item
                break
        
        if not gs_source_dir:
            raise RuntimeError("Could not find extracted Ghostscript directory")
        
        print(f"Found source directory: {gs_source_dir}")
        
        # Try different configure approaches
        configure_attempts = [
            # Minimal configuration first
            [
                "./configure",
                f"--prefix={build_dir.absolute()}"
            ],
            # Fallback with some common options
            [
                "./configure", 
                "--disable-cups",
                "--without-x",
                f"--prefix={build_dir.absolute()}"
            ]
        ]
        
        configure_success = False
        for i, configure_cmd in enumerate(configure_attempts):
            print(f"Configuring build (attempt {i+1})...")
            result = run_command(configure_cmd, cwd=gs_source_dir, check=False)
            if result.returncode == 0:
                configure_success = True
                break
            else:
                print(f"Configure attempt {i+1} failed, trying next...")
        
        if not configure_success:
            raise RuntimeError("All configure attempts failed")
        
        # Build with limited parallelism for stability
        print("Building Ghostscript...")
        run_command(["make", "-j2"], cwd=gs_source_dir)
        
        # Install to build directory
        print("Installing...")
        run_command(["make", "install"], cwd=gs_source_dir)
        
        # Copy the main binary to output directory
        gs_binary = build_dir / "bin" / "gs"
        if gs_binary.exists():
            final_binary = output_dir / "ghostscript"
            shutil.copy2(gs_binary, final_binary)
            
            # Make executable
            os.chmod(final_binary, 0o755)
            
            print(f"Standalone Ghostscript binary created: {final_binary.absolute()}")
            
            # Test the binary
            print("Testing binary...")
            result = run_command([str(final_binary), "--version"], check=False)
            if result.returncode == 0:
                print("Binary test successful!")
                
                # Clean up build artifacts if requested
                if cleanup:
                    print("Cleaning up build artifacts...")
                    if build_dir.exists():
                        shutil.rmtree(build_dir)
                        print(f"Removed build directory: {build_dir}")
                    
                    # Clean up any test files
                    test_files = ["test.ps", "test_original.pdf", "test_prepress.pdf", 
                                 "test_printer.pdf", "test_ebook.pdf", "test_screen.pdf", 
                                 "test_max_compression.pdf", "test_info.pdf"]
                    
                    for test_file in test_files:
                        test_path = Path(test_file)
                        if test_path.exists():
                            test_path.unlink()
                            print(f"Removed test file: {test_file}")
                            
                    print("Cleanup complete!")
                else:
                    print("Build artifacts retained (use --cleanup to remove)")
                
            else:
                print("Binary test failed")
                
        else:
            raise RuntimeError("Ghostscript binary not found after build")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build standalone Ghostscript binary")
    parser.add_argument("--no-cleanup", action="store_true", 
                       help="Keep build artifacts after successful build")
    parser.add_argument("--cleanup", action="store_true", default=True,
                       help="Clean up build artifacts after successful build (default)")
    
    args = parser.parse_args()
    
    # Determine cleanup behavior
    cleanup = not args.no_cleanup
    
    try:
        build_ghostscript(cleanup=cleanup)
        print("Build completed successfully!")
    except Exception as e:
        print(f"Build failed: {e}")
        sys.exit(1)