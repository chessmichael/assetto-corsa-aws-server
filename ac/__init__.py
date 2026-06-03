"""ac — local control tool for the AWS Assetto Corsa server.

Subcommands (see ac/cli.py):
    init    detect your AC install + read terraform outputs
    sync    upload changed server-side content files to S3 (incremental)
    config  interactive wizard -> server.yml
    deploy  render configs, ensure content present, restart the chosen backend
    share   produce the minimal client-side content set for friends
    start   / stop / status / logs / restart   operate the instance via SSM
"""

__version__ = "0.1.0"
