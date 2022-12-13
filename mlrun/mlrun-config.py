import os
import pathlib
import socket
import subprocess
import sys

import click
import dotenv

default_env_file = "~/.mlrun.env"


@click.group()
def main():
    pass


@main.command(context_settings=dict(ignore_unknown_options=True))
@click.option("--background", "-b", is_flag=True, help="run in background process")
@click.option("--port", "-p", help="port to listen on", type=int)
@click.option(
    "--data-volume", "-d", help="path prefix to the location of db and artifacts"
)
@click.option("--verbose", "-v", is_flag=True, help="verbose log")
@click.option("--logs-path", "-l", help="logs directory path")
@click.option(
    "--artifact-path", "-a", help="default artifact path (if not in the data volume)"
)
def local(background, port, data_volume, verbose, logs_path, artifact_path):
    """Install mlrun service as a local process (limited setup, no UI)"""
    env = {"MLRUN_IGNORE_ENV_FILE": "true"}
    cmd = [sys.executable, "-m", "mlrun", "db"]
    data_volume = data_volume or os.environ.get("SHARED_DIR", "")
    artifact_path = artifact_path or os.environ.get("MLRUN_ARTIFACT_PATH", "")

    if background:
        cmd += ["-b"]
    if port is not None:
        cmd += ["-p", str(port)]
    if data_volume is not None:
        cmd += ["-v", data_volume]
        env["MLRUN_HTTPDB__LOGS_PATH"] = data_volume.rstrip("/") + "/logs"
    if logs_path is not None:
        env["MLRUN_HTTPDB__LOGS_PATH"] = logs_path
    if verbose:
        cmd += ["--verbose"]
    if artifact_path:
        cmd += ["-a", artifact_path]

    child = subprocess.Popen(cmd, env=env)
    returncode = child.wait()
    if returncode != 0:
        raise SystemExit(returncode)

    _set_mlrun_env(
        {
            "MLRUN_DBPATH": f"http://localhost:{port or '8080'}",
            "LAST_MLRUN_CONFIG": "local",
        }
    )


@click.option(
    "--env-file",
    "-f",
    default="",
    help="path to the mlrun .env file (defaults to '~/.mlrun.env')",
)
@click.option("--api", "-a", type=str, help="api service url")
@click.option("--artifact-path", "-p", help="default artifacts path")
@click.option("--username", "-u", help="username (for remote access)")
@click.option("--access-key", "-k", help="access key (for remote access)")
@click.option(
    "--env-vars",
    "-e",
    default=[],
    multiple=True,
    help="additional env vars, e.g. -e AWS_ACCESS_KEY_ID=<key-id>",
)
def remote(env_file, api, artifact_path, username, access_key, env_vars):
    pass


def _exec_cmd(cmd, mlrun=False, cwd=None):
    cmd = cmd.split()
    if mlrun:
        cmd = [sys.executable, "-m", "mlrun"] + cmd
    out = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    if out.returncode != 0:
        print(out.stderr.decode("utf-8"), file=sys.stderr)
        print(out.stdout.decode("utf-8"), file=sys.stderr)
        raise Exception(out.stderr.decode("utf-8"))
    return out.stdout.decode("utf-8")


def _get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(0)
    try:
        # doesn't even have to be reachable
        s.connect(("10.254.254.254", 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = "127.0.0.1"
    finally:
        s.close()
    return IP


def _list2dict(lines: list):
    out = {}
    for line in lines:
        i = line.find("=")
        if i == -1:
            continue
        key, value = line[:i].strip(), line[i + 1 :].strip()
        if key is None:
            raise ValueError("cannot find key in line (key=value)")
        value = os.path.expandvars(value)
        out[key] = value
    return out


def _set_mlrun_env(env_vars, env_file=None):
    filename = os.path.expanduser(env_file or default_env_file)
    for key, value in env_vars.items():
        dotenv.set_key(filename, key, value, quote_mode="")


if __name__ == "__main__":
    main()
