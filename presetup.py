from subprocess import run, CalledProcessError
import sys
import os

SWAP_SIZE = "4G"  # Размер swap-раздела
ROOT_SIZE = "100%"  # Размер корневого раздела
HOSTNAME = "myarch"
ROOT_PASSWORD = "password"


def resolve_target_disk() -> str:
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
    print(f"WARNING: All data on {target_disk} will be DELETED!")
    confirm = input("Continue? (y/N): ")
    if confirm.lower() != "y":
        sys.exit(1)

    return target_disk


def partition_disk(target_disk: str) -> None:
    print(f"[2/inf] Разметка диска {target_disk}...")
    try:
        # Создание GPT таблицы
        run(["parted", target_disk, "mklabel", "gpt"], check=True)

        # Корневой раздел
        run([
            "parted", target_disk, "mkpart", "primary", "ext4", "1MiB", ROOT_SIZE
        ], check=True)

        # Swap-раздел (если нужно)
        if SWAP_SIZE != "0":
            run([
                "parted", target_disk, "mkpart", "primary", "linux-swap",
                f"100% -{SWAP_SIZE}", "100%"
            ], check=True)
    except CalledProcessError as e:
        print(f"Ошибка разметки: {e}")
        sys.exit(1)


# === Форматирование и монтирование ===
def format_and_mount():
    print("[2/6] Форматирование и монтирование...")
    root_part = f"{target_disk}1"
    swap_part = f"{target_disk}2" if SWAP_SIZE != "0" else None

    try:
        # Форматирование корневого раздела
        run(["mkfs.ext4", root_part], check=True)
        run(["mount", root_part, "/mnt"], check=True)

        # Создание swap
        if swap_part:
            run(["mkswap", swap_part], check=True)
            run(["swapon", swap_part], check=True)
    except CalledProcessError as e:
        print(f"Ошибка форматирования: {e}")
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
    target_disk = resolve_target_disk()
    partition_disk(target_disk)
    # format_and_mount()
    # install_base_system()
    # configure_system()
    # install_grub()
    # finish()
