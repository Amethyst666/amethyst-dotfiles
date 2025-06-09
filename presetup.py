import re
import sys
from subprocess import run, CalledProcessError

MIN_DISK_SIZE = 10 * 10 ** 3
MIN_PRIMARY_SIZE = 5 * 10 ** 3
EFI_SIZE = 10 ** 3


def parse_size(size: str) -> int:
    size = size.strip().lower()
    if size.endswith("b"):
        size = size[:-1]
    result = 0
    sizes = {
        "k": 10 ** 3,
        "m": 10 ** 6,
        "g": 10 ** 9,
        "t": 10 ** 12,
        "ki": 2 ** 10,
        "mi": 2 ** 20,
        "gi": 2 ** 30,
        "ti": 2 ** 40,
    }
    try:
        for suffix, multiplier in sizes.items():
            if size.endswith(suffix):
                result = multiplier * int(size[:-(len(suffix))])
    except ValueError:
        pass
    if result == 0:
        print(f"Warning: unable to parse size '{size}'")
    return result // 10 ** 6


def resolve_target_disk() -> tuple[str, int]:
    print(f"[1/inf] Disk searching...")
    drive_table = run(["lsblk", "-d", "-o", "name,size,type"], capture_output=True)
    disks = [drive.split()[:-1]
             for drive in drive_table.stdout.decode().strip().split('\n')[1:]
             if drive.split()[-1] == "disk"]
    print(f"Select one of the available drives[1-{len(disks)}]:")
    for i, [dname, dsize] in enumerate(disks):
        print(f"{i + 1}. {dname} {dsize}")
    while True:
        try:
            dnum = int(input()) - 1
            assert (0 <= dnum < len(disks))
        except (ValueError, AssertionError):
            print(f"Incorrect number. Enter a number between 1 and {len(disks)}.")
        else:
            break

    target_disk = f"/dev/{disks[dnum][0]}"
    target_disk_size = parse_size(disks[dnum][1])
    if target_disk_size < MIN_DISK_SIZE:
        print(f"Error: Target disk size is too small ({target_disk_size}MB). At least {MIN_DISK_SIZE}MB is required.")
        sys.exit(1)

    print(f"WARNING: All data on {target_disk} will be DELETED!")
    confirm = input("Continue? (y/N): ").strip().lower()
    if confirm.lower() != "y":
        sys.exit(1)

    return target_disk, target_disk_size


def validate_swap_size(size: str, target_disk_size: int) -> bool:
    pattern = re.compile(r"^\d+[KMGT]i?B$", re.IGNORECASE)
    if size == "0":
        return True
    if not pattern.match(size):
        print("Error: Incorrect swap size format.")
        print("Examples: 500M, 2G, 4GiB")
        return False
    if EFI_SIZE + MIN_PRIMARY_SIZE + parse_size(size) > target_disk_size:
        print(f"Error: Swap size is too big. "
              f"Only {target_disk_size - EFI_SIZE - parse_size(size)}MB is allocated for data.")
        return False
    return True


def partition_disk(target_disk: str, target_disk_size: int) -> bool:
    print(f"[2/inf] Partition disk {target_disk}...")
    while True:
        swap_size = input(f"Enter the size of the swap partition (e.g., 2GiB, 0 to disable): ").strip()
        if validate_swap_size(swap_size, target_disk_size):
            break

    try:
        run(["parted", target_disk, "-s", "mklabel", "gpt"], check=True, capture_output=True)

        run(["parted", target_disk, "mkpart", "ESP",
             "fat32", "1MiB", f"{EFI_SIZE}"], check=True, capture_output=True)
        if swap_size != "0":
            run(["parted", target_disk, "mkpart", "primary",
                 "linux-swap", f"{EFI_SIZE}", f"{EFI_SIZE + parse_size(swap_size)}"], check=True, capture_output=True)
            run(["parted", target_disk, "mkpart", "primary",
                 "ext4", f"{EFI_SIZE + parse_size(swap_size)}", "100%"], check=True, capture_output=True)
        else:
            run(["parted", target_disk, "mkpart", "primary",
                 "ext4", f"{EFI_SIZE}", "100%"], check=True, capture_output=True)
    except CalledProcessError as e:
        print(f"Error: {e}")
        sys.exit(1)

    return swap_size != "0"


def format_and_mount(target_disk: str, has_swap: bool) -> None:
    print("[3/inf] Formatting and mounting...")
    efi_part = f"{target_disk}1"
    if has_swap:
        swap_part = f"{target_disk}2"
        root_part = f"{target_disk}3"
    else:
        root_part = f"{target_disk}2"

    try:
        run(["mkfs.fat", "-F", "32", efi_part], check=True, capture_output=True)
        run(["mkfs.ext4", root_part], check=True, capture_output=True)
        run(["mount", root_part, "/mnt"], check=True, capture_output=True)
        run(["mkdir", "/mnt/boot"], check=True, capture_output=True)
        run(["mount", efi_part, "/mnt/boot"], check=True, capture_output=True)

        if has_swap:
            run(["mkswap", swap_part], check=True, capture_output=True)
            run(["swapon", swap_part], check=True, capture_output=True)
    except CalledProcessError as e:
        print(f"Error: {e}")
        sys.exit(1)


# === Установка базовой системы ===
def install_base_system():
    print("[3/6] Установка базовой системы...")
    try:
        run([
            "pacstrap", "/mnt", "base", "base-devel", "linux", "linux-firmware",
            "networkmanager", "vim", "python"
        ], check=True)
    except CalledProcessError as e:
        print(f"Ошибка установки: {e}")
        sys.exit(1)


# === Настройка системы ===
def configure_system():
    print("[4/6] Настройка системы...")
    try:
        # Генерация fstab
        run(["genfstab", "-U", "/mnt"], stdout=open("/mnt/etc/fstab", "w"), check=True)

        # Внутренние команды через chroot
        chroot_commands = [
            f"echo '{HOSTNAME}' > /etc/hostname",
            "ln -sf /usr/share/zoneinfo/Europe/Moscow /etc/localtime",
            "hwclock --systohc",
            "echo 'en_US.UTF-8 UTF-8' > /etc/locale.gen",
            "locale-gen",
            "echo 'LANG=en_US.UTF-8' > /etc/locale.conf",
            f"echo 'root:{ROOT_PASSWORD}' | chpasswd"
        ]

        with open("/mnt/root/setup.sh", "w") as f:
            f.write("#!/bin/bash\n")
            f.write("\n".join(chroot_commands))

        run(["chmod", "+x", "/mnt/root/setup.sh"], check=True)
        run(["arch-chroot", "/mnt", "/root/setup.sh"], check=True)
    except CalledProcessError as e:
        print(f"Ошибка настройки: {e}")
        sys.exit(1)


# === Установка GRUB ===
def install_grub():
    print("[5/6] Установка GRUB...")
    try:
        run(["pacstrap", "/mnt", "grub"], check=True)
        run(["arch-chroot", "/mnt", "grub-install", "--target=i386-pc", target_disk], check=True)
        run(["arch-chroot", "/mnt", "grub-mkconfig", "-o", "/boot/grub/grub.cfg"], check=True)
    except CalledProcessError as e:
        print(f"Ошибка установки GRUB: {e}")
        sys.exit(1)


# === Завершение ===
def finish():
    print("[6/6] Установка завершена. Перезагрузите систему.")
    run(["umount", "-R", "/mnt"], check=True)
    if SWAP_SIZE != "0":
        run(["swapoff", "-a"], check=True)


def presetup() -> None:
    target_disk, target_disk_size = resolve_target_disk()
    has_swap = partition_disk(target_disk, target_disk_size)
    format_and_mount(target_disk, has_swap)
    # install_base_system()
    # configure_system()
    # install_grub()
    # finish()
