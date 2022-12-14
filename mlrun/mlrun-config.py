import os
import pathlib
import socket
import subprocess
import sys

import click
import dotenv

default_env_file = "~/.mlrun.env"


# common options
env_file_opt = click.option(
    "--env-file",
    "-f",
    default="",
    help="path to the mlrun .env file (defaults to '~/.mlrun.env')",
)
env_vars_opt = click.option(
    "--env-vars",
    "-e",
    default=[],
    multiple=True,
    help="additional env vars, e.g. -e AWS_ACCESS_KEY_ID=<key-id>",
)
foreground_opt = click.option(
    "--foreground",
    is_flag=True,
    default=False,
    help="run process in the foreground (not as a daemon)",
)


@click.group()
def main():
    """MLRun configuration utility"""
    pass


@main.command()
@click.option(
    "--data-volume", "-d", help="path prefix to the location of db and artifacts"
)
@click.option("--logs-path", "-l", help="logs directory path")
@click.option(
    "--artifact-path", "-a", help="default artifact path (if not in the data volume)"
)
@foreground_opt
@click.option("--port", "-p", help="port to listen on", type=int)
@env_vars_opt
@env_file_opt
@click.option("--force-local", is_flag=True, help="force use of local or docker mlrun")
@click.option("--verbose", "-v", is_flag=True, help="verbose log")
def start(
    data_volume, logs_path, artifact_path, foreground, port, env_vars, env_file, force_local, verbose
):
    """Start MLRun service, auto detect the best method (local/docker/k8s/remote)"""
    current_env_vars = _get_mlrun_env(env_file)
    last_deployment = current_env_vars.get("LAST_MLRUN_DEPLOYMENT", "")
    if not force_local and (os.environ.get("V3IO_ACCESS_KEY", "") or last_deployment == "remote"):
        dbpath = current_env_vars.get("MLRUN_DBPATH") or os.environ.get("MLRUN_DBPATH", "")
        print(f"detected settings of remote MLRun service at {dbpath}")
        return

    # todo check if local and pid is alive
    
    _local(
        data_volume,
        logs_path,
        artifact_path,
        foreground,
        port,
        env_vars,
        env_file,
        verbose,
    )


@main.command()
@click.option(
    "--data-volume", "-d", help="path prefix to the location of db and artifacts"
)
@click.option("--logs-path", "-l", help="logs directory path")
@click.option(
    "--artifact-path", "-a", help="default artifact path (if not in the data volume)"
)
@foreground_opt
@click.option("--port", "-p", help="port to listen on", type=int)
@env_vars_opt
@env_file_opt
@click.option("--verbose", "-v", is_flag=True, help="verbose log")
def local(
    data_volume, logs_path, artifact_path, foreground, port, env_vars, env_file, verbose
):
    """Install MLRun service as a local process (limited, no UI and Nuclio)"""
    _local(
        data_volume,
        logs_path,
        artifact_path,
        foreground,
        port,
        env_vars,
        env_file,
        verbose,
    )


def _local(
    data_volume, logs_path, artifact_path, foreground, port, env_vars, env_file, verbose
):
    env = {"MLRUN_IGNORE_ENV_FILE": "true"}
    cmd = [sys.executable, "-m", "mlrun", "db"]
    data_volume = data_volume or os.environ.get("SHARED_DIR", "")
    artifact_path = artifact_path or os.environ.get("MLRUN_ARTIFACT_PATH", "")

    if not port and "COLAB_RELEASE_TAG" in os.environ:
        # change default port due to conflict in google colab
        port = 8089

    if not foreground:
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
            "MLRUN_MOCK_NUCLIO_DEPLOYMENT": "auto",
            "LAST_MLRUN_DEPLOYMENT": "local",
        },
        env_file=env_file,
        env_vars=env_vars,
    )


@main.command()
@click.option(
    "--data-volume", "-d", help="path prefix to the location of db and artifacts"
)
@click.option(
    "--artifact-path", "-a", help="default artifact path (if not in the data volume)"
)
@foreground_opt
@click.option("--port", "-p", help="MLRun port to listen on", type=int, default="8080")
@env_vars_opt
@env_file_opt
@click.option("--compose-file", help="path to save the generated compose.yaml file")
def docker(
    data_volume,
    artifact_path,
    foreground,
    port,
    env_vars,
    env_file,
    compose_file,
):
    """Deploy mlrun and nuclio services using Docker compose"""
    if not _has_docker():
        print(
            "Docker command not detected on this system, use local or remore service options"
        )
        raise SystemExit(1)

    compose_body = compose_template
    compose_file = compose_file or "compose.yaml"
    with open(compose_file, "w") as fp:
        fp.write(compose_body)

    data_volume = os.path.realpath(os.path.expanduser(data_volume or "~/mlrun-data"))
    host_mnt_dir = data_volume
    os.makedirs(data_volume, exist_ok=True)

    env = os.environ.copy()
    for key, val in {
        "HOST_IP": _get_ip(),
        "SHARED_DIR": data_volume,
        "HOST_MNT_DIR": host_mnt_dir,
        "MLRUN_PORT": str(port),
    }.items():
        env[key] = val

    cmd = ["docker-compose", "-f", compose_file, "up"]
    if not foreground:
        cmd += ["-d"]
    child = subprocess.Popen(cmd, env=env)
    returncode = child.wait()
    if returncode != 0:
        raise SystemExit(returncode)

    env_file = _set_mlrun_env(
        {
            "MLRUN_DBPATH": f"http://localhost:{port}",
            "MLRUN_MOCK_NUCLIO_DEPLOYMENT": "auto",
            "LAST_MLRUN_DEPLOYMENT": "docker",
            "MLRUN_COMPOSE_PATH": compose_file,
        },
        env_file=env_file,
        env_vars=env_vars,
    )


@main.command()
@click.argument("url", type=str, default="", required=True)
@click.option("--username", "-u", help="username (for secure access)")
@click.option("--access-key", "-k", help="access key (for secure access)")
@click.option("--artifact-path", "-p", help="default artifacts path")
@env_file_opt
@env_vars_opt
def remote(url, username, access_key, artifact_path, env_file, env_vars):
    """Connect to remote MLRun service (over Kubernetes)"""
    config = {"MLRUN_DBPATH": url, "LAST_MLRUN_DEPLOYMENT": "remote"}
    if artifact_path:
        config["V3IO_USERNAME"] = username
    if artifact_path:
        config["V3IO_ACCESS_KEY"] = access_key
    if artifact_path:
        config["MLRUN_ARTIFACT_PATH"] = artifact_path
    _set_mlrun_env(config, env_file=env_file, env_vars=env_vars)


@main.command()
@env_file_opt
@env_vars_opt
def kubernetes(env_file, env_vars):
    """Install MLRun service on Kubernetes"""
    print(
        "see instructions in MLRun doc site at https://docs.mlrun.org/en/stable/install/kubernetes.html"
    )


@main.command()
@click.option("--api", "-a", type=str, help="api service url")
@click.option("--username", "-u", help="username (for secure access)")
@click.option("--access-key", "-k", help="access key (for secure access)")
@click.option("--artifact-path", "-p", help="default artifacts path")
@env_file_opt
@env_vars_opt
def set(api, username, access_key, artifact_path, env_file, env_vars):
    """Set configuration in mlrun default or specified .env file"""
    filename = os.path.expanduser(env_file or default_env_file)
    if not os.path.isfile(filename):
        print(f".env file {filename} not found, creating new and setting configuration")
    else:
        print(f"updating configuration in .env file {filename}")
    env_dict = {
        "MLRUN_DBPATH": api,
        "MLRUN_ARTIFACT_PATH": artifact_path,
        "V3IO_USERNAME": username,
        "V3IO_ACCESS_KEY": access_key,
    }
    _set_mlrun_env(env_dict, env_file=env_file, env_vars=env_vars)


@main.command()
@env_file_opt
@click.option("--api", "-a", type=str, help="api service url")
@click.option("--username", "-u", help="username (for remote access)")
@click.option("--access-key", "-k", help="access key (for remote access)")
def get(env_file, api, username, access_key):
    """Print the local or remote configuration"""
    if env_file and not os.path.isfile(os.path.expanduser(env_file)):
        print(f"error, env file {env_file} does not exist")
        exit(1)

    import mlrun

    if env_file or api:
        mlrun.set_environment(
            api,
            access_key=access_key,
            username=username,
            env_file=env_file,
        )
    print(mlrun.mlconf.dump_yaml())


@main.command()
@env_file_opt
def clear(env_file):
    """Delete the default or specified config .env file"""
    filename = os.path.expanduser(env_file or default_env_file)
    if not os.path.isfile(filename):
        print(f".env file {filename} not found")
    else:
        print(f"deleting .env file {filename}")
        os.remove(filename)


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


def _set_mlrun_env(env_vars, env_file=None, env_vars_opt=None):
    filename = os.path.expanduser(env_file or default_env_file)
    for key, value in env_vars.items():
        dotenv.set_key(filename, key, value, quote_mode="")
    if env_vars_opt:
        for key, value in _list2dict(env_vars_opt).items():
            dotenv.set_key(filename, key, value, quote_mode="")
    if env_file:
        # if its not the default file print the usage details
        print(
            f"to use the {env_file} .env file add MLRUN_ENV_FILE={env_file} to your development environment\n"
            f"or call `mlrun.set_env_from_file({env_file}) in the beginning of your code"
        )
    return filename


def _get_mlrun_env(env_file=None):
    filename = os.path.expanduser(env_file or default_env_file)
    return dotenv.dotenv_values(filename)


def _has_docker():
    child = subprocess.Popen(
        ["docker", "ps"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    returncode = child.wait()
    return returncode == 0


def _pid_exists(pid):
    """Check whether pid exists in the current process table."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


compose_template = """
services:
  init_nuclio:
    image: alpine:3.16
    command:
      - "/bin/sh"
      - "-c"
      - |
        mkdir -p /etc/nuclio/config/platform; \
        cat << EOF | tee /etc/nuclio/config/platform/platform.yaml
        runtime:
          common:
            env:
              MLRUN_DBPATH: http://mlrun-api:8080
        local:
          defaultFunctionContainerNetworkName: mlrun
          defaultFunctionRestartPolicy:
            name: always
            maxRetryCount: 0
          defaultFunctionVolumes:
            - volume:
                name: mlrun-stuff
                hostPath:
                  path: ${HOST_MNT_DIR}
              volumeMount:
                name: mlrun-stuff
                mountPath: ${SHARED_DIR}
        logger:
          sinks:
            myStdoutLoggerSink:
              kind: stdout
          system:
            - level: debug
              sink: myStdoutLoggerSink
          functions:
            - level: debug
              sink: myStdoutLoggerSink
        EOF
    volumes:
      - nuclio-platform-config:/etc/nuclio/config

  mlrun-api:
    image: "mlrun/mlrun-api:${TAG:-1.2.0}"
    ports:
      - "${MLRUN_PORT:-8080}:8080"
    environment:
      MLRUN_ARTIFACT_PATH: "${SHARED_DIR}/{{project}}"
      # using local storage, meaning files / artifacts are stored locally, so we want to allow access to them
      MLRUN_HTTPDB__REAL_PATH: /data
      MLRUN_HTTPDB__DATA_VOLUME: "${SHARED_DIR}"
      MLRUN_LOG_LEVEL: DEBUG
      MLRUN_NUCLIO_DASHBOARD_URL: http://nuclio:${NUCLIO_PORT:-8070}
      MLRUN_HTTPDB__DSN: "sqlite:////data/mlrun.db?check_same_thread=false"
      MLRUN_UI__URL: http://localhost:${MLRUN_UI_PORT:-8060}
      # not running on k8s meaning no need to store secrets
      MLRUN_SECRET_STORES__KUBERNETES__AUTO_ADD_PROJECT_SECRETS: "false"
      # let mlrun control nuclio resources
      MLRUN_HTTPDB__PROJECTS__FOLLOWERS: "nuclio"
    volumes:
      - "${HOST_MNT_DIR:?err}:/data"
    networks:
      - mlrun

  mlrun-ui:
    image: "mlrun/mlrun-ui:${TAG:-1.2.0}"
    ports:
      - "{MLRUN_UI_PORT:-8060}:8090"
    environment:
      MLRUN_API_PROXY_URL: http://mlrun-api:8080
      MLRUN_NUCLIO_MODE: enable
      MLRUN_NUCLIO_API_URL: http://nuclio:8070
      MLRUN_NUCLIO_UI_URL: http://localhost:${NUCLIO_PORT:-8070}
    networks:
      - mlrun

  nuclio:
    image: "quay.io/nuclio/dashboard:${NUCLIO_TAG:-stable-amd64}"
    ports:
      - "${NUCLIO_PORT:-8070}:8070"
    environment:
      NUCLIO_DASHBOARD_EXTERNAL_IP_ADDRESSES: "${HOST_IP}"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - nuclio-platform-config:/etc/nuclio/config
    depends_on:
      - init_nuclio
    networks:
      - mlrun

volumes:
  nuclio-platform-config: {}

networks:
  mlrun:
    name: mlrun
"""

if __name__ == "__main__":
    main()
