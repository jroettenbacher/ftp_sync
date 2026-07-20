#!/usr/bin/env python
"""
| *created*: 17.07.26
| *author*: Johannes Röttenbacher, translated from ftp_sync.py by Qwen 3.6 35B A3B

SFTP Directory Synchronization Script

A command-line utility for synchronizing a local directory to a remote SFTP server.
It recursively mirrors directory structures, uploads changed or new files based on
size comparison, and removes remote files that no longer exist locally. Supports
force-uploading and provides real-time progress tracking.

Features:
    - Recursive directory mirroring and creation
    - Incremental file uploads (size-based change detection)
    - Force mode to overwrite all remote files
    - Automatic cleanup of orphaned remote files
    - Secure SFTP connection via Paramiko
    - Progress tracking with tqdm

Dependencies:
    - paramiko
    - python-dotenv
    - tqdm

Environment Variables:
    - SFTP_HOST: SFTP server hostname or IP address
    - SFTP_PORT: SSH/SFTP port (default: 22)
    - SFTP_USERNAME: Authentication username
    - SFTP_PASSWORD: Authentication password
    - SFTP_PATH: Remote directory path to sync to
    - LOCAL_SITE_PATH: Local directory path to sync from

Usage:
    python sftp_sync.py [--force]

Options:
    -f, --force    Force upload of all local files, overwriting remote counterparts

License: MIT
"""
import argparse
import datetime
import os
from pathlib import Path, PurePosixPath
from tqdm import tqdm
import paramiko
from dotenv import load_dotenv


def get_remote_dirs(sftp, path):
    """Recursively collect all remote directories."""
    remote_dirs = []

    def recursive_get_dirs(sftp, current_path):
        remote_dirs.append(PurePosixPath(current_path))
        entries = sftp.listdir_attr(str(current_path))
        for entry in entries:
            # Filter out '.' and '..', check if it's a directory
            if entry.filename not in ('.', '..') and (entry.st_mode & 0o40000):
                recursive_get_dirs(sftp, PurePosixPath(current_path) / entry.filename)
    recursive_get_dirs(sftp, path)
    return remote_dirs


def get_remote_files(sftp, path):
    """Collect all remote files with modification time and size."""
    remote_files = []
    remote_dirs = get_remote_dirs(sftp, path)
    for dir_path in remote_dirs:
            entries = sftp.listdir_attr(str(dir_path))
            for entry in entries:
                if entry.filename not in ('.', '..') and not (entry.st_mode & 0o40000):
                    remote_files.append((
                        PurePosixPath(dir_path) / entry.filename,
                        datetime.datetime.fromtimestamp(entry.st_mtime),
                        entry.st_size
                    ))
    return remote_files


def delete_remote_files_not_in_local(sftp, remote_files, local_files, local_site_path, sftp_path):
    """Delete remote files that do not exist in the local directory structure."""
    local_file_paths = {Path(f).relative_to(local_site_path) for f in local_files.keys()}
    remote_file_paths = {Path(f[0]).relative_to('.') for f in remote_files}
    files_to_delete = remote_file_paths - local_file_paths

    if not files_to_delete:
        print("\U0001F937 No remote files to delete.")
        return

    print(f"Deleting {len(files_to_delete)} remote file(s) not present locally...")
    for remote_file in tqdm(files_to_delete, desc="🗑 Deleting remote files"):
        remote_full_path = Path(sftp_path) / remote_file
        try:
            sftp.remove(remote_full_path.as_posix())
            tqdm.write(f"Deleted: {remote_full_path}")
        except Exception as e:
            tqdm.write(f"Failed to delete {remote_full_path}: {e}")


def ensure_remote_dir(sftp, path):
    """Recursively create directories on the SFTP server if they don't exist."""
    parts = PurePosixPath(path).parts
    current = '/'
    for part in parts:
        current = PurePosixPath(current) / part
        try:
            sftp.stat(current.as_posix())
        except Exception:
            sftp.mkdir(current.as_posix())


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(prog='sftp_sync.py',
                                     description='Sync a local directory to an SFTP server.',
                                     epilog='LICENSE: MIT')
    parser.add_argument(
        '-f', '--force',
        action='store_true',
        help='Force upload of local files and overwrite remote files.'
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_arguments()
    load_dotenv()

    # SFTP server settings (SFTP uses SSH, typically port 22)
    sftp_host = os.environ.get('SFTP_HOST')
    sftp_port = int(os.environ.get('SFTP_PORT', 22))
    sftp_username = os.environ['SFTP_USERNAME']
    sftp_password = os.environ['SFTP_PASSWORD']
    sftp_path = os.environ['SFTP_PATH']

    # Local site settings
    local_site_path = os.environ['LOCAL_SITE_PATH']

    # Create SSH and SFTP clients
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        print('\U0001F310 Connecting to SFTP server...')
        ssh.connect(sftp_host,
                    port=sftp_port,
                    username=sftp_username,
                    password=sftp_password,
                    look_for_keys=False,  # Stops scanning ~/.ssh/ for keys
                    allow_agent=False  # Stops querying your system's SSH agent
        )
        sftp = ssh.open_sftp()
        sftp.chdir(sftp_path)

        print('\N{thought balloon} Getting remote files...')
        remote_files = get_remote_files(sftp, '.')

        print('\U0001F4C2 Getting local files...')
        local_files = {}
        for root, dirs, files in Path(local_site_path).walk():
            for file in files:
                filepath = Path(root) / file
                local_files[filepath] = {
                    'modify': datetime.datetime.fromtimestamp(os.path.getmtime(filepath)),
                    'size': os.path.getsize(filepath)
                }

        if args.force:
            print("⚠️ Force option given. Uploading all local files.")
            changed_files = local_files.keys()
        else:
            print('\U0001F440 Looking for changes...')
            changed_files = []
            for local_file, local_file_info in local_files.items():
                remote_file = Path(local_file).relative_to(local_site_path)
                remote_file_info = next((f for f in remote_files if Path(f[0]).relative_to('.') == remote_file), None)
                if remote_file_info is None or (int(remote_file_info[2]) != local_file_info['size']):
                    changed_files.append(local_file)

        print('\U0001FA9E Mirroring directories...')
        local_dirs = []
        for root, dirs, _ in Path(local_site_path).walk():
            for d in dirs:
                local_dirs.append((Path(root) / d).relative_to(local_site_path))

        for d in local_dirs:
            ensure_remote_dir(sftp, d)

        print('\U0001F6D2 Uploading files...')
        for file in tqdm(changed_files, desc='Uploading'):
            tqdm.write(file.as_posix())
            remote_file_path = Path(sftp_path) / Path(file).relative_to(local_site_path)
            try:
                sftp.put(str(file), str(remote_file_path))
            except Exception as e:
                tqdm.write(f"Failed to upload {file}: {e}")

        print("\U0001F5D1 Checking for remote files to delete...")
        delete_remote_files_not_in_local(sftp, remote_files, local_files, local_site_path, sftp_path)

        sftp.close()
        ssh.close()

    except Exception as e:
        print(f'\U0001F92F Error uploading to SFTP server: {e}')
    finally:
        print('\U0001F4AF Finished with sftp_sync.py \n'
              '\U0001F9DA \U0001F44B Have a great day!')
