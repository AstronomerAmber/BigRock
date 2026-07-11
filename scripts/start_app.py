import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

BACKEND_READY = [r"Uvicorn running on", r"Application startup complete", r"Started server process"]
FRONTEND_READY = [r"Server is running on http://localhost", r"Ready"]


def _port_available(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            sock.connect(("localhost", port))
        return False
    except (ConnectionRefusedError, OSError):
        return True


class ProcessManager:
    def __init__(self, port: int = 8000, no_ui: bool = False):
        self.port = port
        self.no_ui = no_ui
        self.backend_process = None
        self.frontend_process = None
        self.backend_ready = False
        self.frontend_ready = False
        self.failed = threading.Event()
        self.backend_log = None
        self.frontend_log = None

    def check_ports(self) -> None:
        if os.environ.get("DATABRICKS_APP_NAME"):
            return
        errors = []
        if not _port_available(self.port):
            errors.append(f"Port {self.port} is already in use.")
        if not self.no_ui:
            frontend_port = int(os.environ.get("CHAT_APP_PORT", os.environ.get("PORT", "3000")))
            if frontend_port == self.port:
                errors.append("Backend and frontend ports must be different.")
            elif not _port_available(frontend_port):
                errors.append(f"Port {frontend_port} is already in use.")
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            sys.exit(1)

    def clone_frontend_if_needed(self) -> bool:
        frontend_dir = Path("e2e-chatbot-app-next")
        if frontend_dir.exists():
            return True

        print("Cloning Databricks chat frontend...")
        try:
            subprocess.run(
                ["git", "clone", "--filter=blob:none", "--sparse", "https://github.com/databricks/app-templates.git", "temp-app-templates"],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "sparse-checkout", "set", "e2e-chatbot-app-next"],
                cwd="temp-app-templates",
                check=True,
                capture_output=True,
                text=True,
            )
            Path("temp-app-templates/e2e-chatbot-app-next").rename(frontend_dir)
            shutil.rmtree("temp-app-templates", ignore_errors=True)
            return True
        except subprocess.CalledProcessError as exc:
            print(f"Failed to clone frontend: {exc.stderr or exc.stdout}")
            shutil.rmtree("temp-app-templates", ignore_errors=True)
            return False

    def monitor_process(self, process, name: str, log_file, patterns: list[str]) -> None:
        ready = False
        try:
            for line in iter(process.stdout.readline, ""):
                if not line:
                    break
                line = line.rstrip()
                log_file.write(line + "\n")
                print(f"[{name}] {line}")
                if not ready and any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns):
                    ready = True
                    if name == "backend":
                        self.backend_ready = True
                    else:
                        self.frontend_ready = True
                    print(f"{name} is ready")
            process.wait()
            if process.returncode != 0:
                self.failed.set()
        except Exception as exc:
            print(f"Error monitoring {name}: {exc}")
            self.failed.set()

    def start_process(self, cmd: list[str], name: str, log_file, patterns: list[str], cwd: Path | None = None):
        print(f"Starting {name}: {' '.join(cmd)}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=cwd,
        )
        thread = threading.Thread(
            target=self.monitor_process,
            args=(process, name, log_file, patterns),
            daemon=True,
        )
        thread.start()
        return process

    def print_logs(self, path: str) -> None:
        print(f"\nLast 80 lines of {path}:")
        print("-" * 40)
        try:
            lines = Path(path).read_text().splitlines()
            print("\n".join(lines[-80:]))
        except FileNotFoundError:
            print("(no log file found)")
        print("-" * 40)

    def cleanup(self) -> None:
        for process in [self.backend_process, self.frontend_process]:
            if process:
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    process.kill()
        if self.backend_log:
            self.backend_log.close()
        if self.frontend_log:
            self.frontend_log.close()

    def run(self, backend_args: list[str] | None = None) -> int:
        load_dotenv(dotenv_path=Path(".env"), override=True)
        self.check_ports()

        if not self.no_ui:
            if not self.clone_frontend_if_needed():
                print("Frontend unavailable; running backend only.")
                self.no_ui = True
            else:
                os.environ["API_PROXY"] = f"http://localhost:{self.port}/invocations"

        self.backend_log = open("backend.log", "w", buffering=1)
        if not self.no_ui:
            self.frontend_log = open("frontend.log", "w", buffering=1)

        try:
            backend_cmd = ["python", "-m", "agent_server.start_server"]
            if backend_args:
                backend_cmd.extend(backend_args)
            self.backend_process = self.start_process(
                backend_cmd,
                "backend",
                self.backend_log,
                BACKEND_READY,
            )

            if not self.no_ui:
                frontend_dir = Path("e2e-chatbot-app-next")
                for cmd in [["npm", "install"], ["npm", "run", "build"]]:
                    result = subprocess.run(cmd, cwd=frontend_dir, capture_output=True, text=True)
                    if result.returncode != 0:
                        print(result.stdout)
                        print(result.stderr)
                        return result.returncode
                self.frontend_process = self.start_process(
                    ["npm", "run", "start"],
                    "frontend",
                    self.frontend_log,
                    FRONTEND_READY,
                    cwd=frontend_dir,
                )

            while not self.failed.is_set():
                time.sleep(0.1)
                if self.backend_process.poll() is not None:
                    self.failed.set()
                if not self.no_ui and self.frontend_process and self.frontend_process.poll() is not None:
                    self.failed.set()

            failed_name = "backend" if self.no_ui or self.backend_process.poll() is not None else "frontend"
            failed_process = self.backend_process if failed_name == "backend" else self.frontend_process
            exit_code = failed_process.returncode if failed_process else 1
            print(f"{failed_name} exited with code {exit_code}")
            self.print_logs("backend.log")
            if not self.no_ui:
                self.print_logs("frontend.log")
            return exit_code or 1
        except KeyboardInterrupt:
            return 0
        finally:
            self.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Start Bobabricks agent backend and chat frontend.")
    parser.add_argument("--no-ui", action="store_true", help="Run the backend only.")
    args, backend_args = parser.parse_known_args()

    port = 8000
    for idx, arg in enumerate(backend_args):
        if arg == "--port" and idx + 1 < len(backend_args):
            try:
                port = int(backend_args[idx + 1])
            except ValueError:
                pass
            break

    sys.exit(ProcessManager(port=port, no_ui=args.no_ui).run(backend_args))


if __name__ == "__main__":
    main()
