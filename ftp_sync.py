import argparse
import datetime
import ftplib
from dotenv import load_dotenv
import os
from pathlib import PurePosixPath, Path
from tqdm import tqdm


def get_remote_dirs(ftp_client, path):
    remote_dirs = []
    def recursive_get_dirs(ftp_client, path):
        remote_dirs.append(PurePosixPath(path))
        for file_info in ftp_client.mlsd(path=PurePosixPath(path), facts=['type']):
            if file_info[1]['type'] == 'dir':
                recursive_get_dirs(ftp_client, PurePosixPath(path) / file_info[0])
    recursive_get_dirs(ftp_client, path)
    return remote_dirs


def get_remote_files(ftp_client, path):
    remote_files = []
    remote_dirs = get_remote_dirs(ftp_client, path)
    for dir in remote_dirs:
        remote_file_list = ftp_client.mlsd(path=str(dir), facts=['size', 'modify', 'type'])
        remote_files = remote_files + [(Path(dir) / f[0], f[1]['modify'], f[1]['size']) for f in remote_file_list if f[1]['type'] == 'file']
    return remote_files


def delete_remote_files_not_in_local(ftp_client, remote_files, local_files, local_site_path, ftp_path):
    """
    Delete remote files that do not exist in the local directory structure.
    """
    # Create a set of relative paths of local files (relative to local_site_path)
    local_file_paths = {Path(f).relative_to(local_site_path) for f in local_files.keys()}

    # Get remote file paths (relative to ftp_path)
    remote_file_paths = {Path(f[0]).relative_to('.') for f in remote_files}

    # Find remote files that are not in local
    files_to_delete = remote_file_paths - local_file_paths

    if not files_to_delete:
        print("\U0001F937 No remote files to delete.")
        return

    print(f"Deleting {len(files_to_delete)} remote file(s) not present locally...")
    for remote_file in tqdm(files_to_delete, desc="🗑 Deleting remote files"):
        remote_full_path = Path(ftp_path) / remote_file
        try:
            ftp_client.delete(remote_full_path.as_posix())
            tqdm.write(f"Deleted: {remote_full_path}")
        except ftplib.error_perm as e:
            tqdm.write(f"Failed to delete {remote_full_path}: {e}")
        except Exception as e:
            tqdm.write(f"Unexpected error deleting {remote_full_path}: {e}")


def parse_arguments():
    """
    Parse command line arguments.

    Returns:
        argparse.Namespace: Objekt mit den Argumenten (inkl. force).
    """
    parser = argparse.ArgumentParser(prog='ftp_sync.py',
                    description='Sync a local directory to an FTP server.',
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

    # FTP server settings
    ftp_host = os.environ['FTP_HOST']
    ftp_username = os.environ['FTP_USERNAME']
    ftp_password = os.environ['FTP_PASSWORD']
    ftp_path = os.environ['FTP_PATH']

    # Local site settings
    local_site_path = 'output'

    # Create an FTP client
    ftp_client = ftplib.FTP_TLS()

    try:
        # Connect to the FTP server using a TLS secured connection
        print('\U0001F310 Connecting to FTP server...')
        ftp_client.connect(ftp_host, 21)
        ftp_client.login(ftp_username, ftp_password)
        ftp_client.prot_p()
        ftp_client.cwd(ftp_path)

        # Get the list of files and directories on the FTP server
        print('\N{thought balloon} Getting remote files...')
        remote_files = get_remote_files(ftp_client, '.')
        # Get the list of files on the local machine with modification dates
        print('\U0001F4C2 Getting local files...')
        local_files = {}
        for root, dirs, files in Path(local_site_path).walk():
            for file in files:
                filepath = Path(root) / file
                local_files[filepath] = {'modify': datetime.datetime.fromtimestamp(os.path.getmtime(filepath)),
                                         'size': os.path.getsize(filepath)}

        # Find the files that have changed on the local machine
        print('\U0001F440 Looking for changes...')
        changed_files = []
        for local_file, local_file_info in local_files.items():
            remote_file = Path(local_file).relative_to(local_site_path)
            remote_file_info = next((file for file in remote_files if Path(file[0]).relative_to('.') == remote_file), None)
            if remote_file_info is None or (int(remote_file_info[2]) < local_file_info['size']):
                changed_files.append(local_file)

        if args.force:
            # Upload all local files
            print("⚠️ Force option given. Uploading all local files.")
            changed_files = local_files.keys()

        # Create directories if not yet present
        print('\U0001FA9E Mirroring directories...')
        local_dirs = []
        for root, dirs, _ in Path(local_site_path).walk():
            for d in dirs:
                local_dirs.append((Path(root) / d).relative_to('output'))

        remote_dirs = []  # initialize the list in case there are no remote dirs
        remote_dirs = [Path(d).relative_to(ftp_path) for d in get_remote_dirs(ftp_client, ftp_path)]
        for d in local_dirs:
            if d not in remote_dirs:
                ftp_client.mkd(d.as_posix())

        # Upload the new local files to the FTP server
        for file in tqdm(changed_files, desc='\U0001F6D2 Uploading files'):
            tqdm.write(file.as_posix())
            remote_file_path = Path(ftp_path) / Path(file).relative_to(local_site_path)
            with open(file, 'rb') as file_object:
                ftp_client.storbinary(f'STOR {remote_file_path.as_posix()}', file_object)

        # Now delete remote files that are not in local
        print("\U0001F5D1 Checking for remote files to delete...")
        delete_remote_files_not_in_local(ftp_client, remote_files, local_files, local_site_path, ftp_path)

        # Close the FTP client
        ftp_client.quit()

    except Exception as e:
        print(f'\U0001F92F Error uploading to FTP server: {e}')

    finally:
        print('\U0001F4AF Finished with ftp_upload.py \n'
              '\U0001F9DA \U0001F44B Have a great day!')