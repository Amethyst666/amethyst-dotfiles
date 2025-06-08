import os
import subprocess
import sys

from presetup import presetup


def check_root():
    if os.geteuid() != 0:
        print("Error: run the script with root privileges!")
        sys.exit(1)


def check_internet():
    try:
        subprocess.run(["ping", "-c", "1", "archlinux.org"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print("Error: no internet connection!")
        sys.exit(1)


if __name__ == "__main__":
    check_root()
    check_internet()
    presetup()