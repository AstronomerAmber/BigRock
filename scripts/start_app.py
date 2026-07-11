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

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False

BACKEND_READY = [r"Uvicorn running on", r"Application startup complete", r"Started server process"]
FRONTEND_READY = [r"Server is running on http://localhost", r"Ready"]


BOBABRICKS_APP_SIDEBAR = r"""import { useNavigate } from 'react-router-dom';
import { Link } from 'react-router-dom';

import { SidebarHistory } from '@/components/sidebar-history';
import { SidebarUserNav } from '@/components/sidebar-user-nav';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { DbIcon } from '@/components/ui/db-icon';
import { NewChatIcon, SidebarCollapseIcon, SidebarExpandIcon } from '@/components/icons';
import { cn } from '@/lib/utils';
import type { ClientSession } from '@chat-template/auth';
import { Action } from './elements/actions';

function StatusDot({ tone = 'green' }: { tone?: 'green' | 'amber' }) {
  return (
    <span
      className={cn(
        'mt-1 size-2 shrink-0 rounded-full',
        tone === 'green' ? 'bg-emerald-500' : 'bg-amber-500',
      )}
    />
  );
}

function BobabricksResourcePanel() {
  const tools = [
    ['Genie Agent', 'governed store metrics'],
    ['StoreTime', 'training schedules and converted hours'],
    ['OpsTask', 'approval-gated follow-ups'],
    ['Confluence', 'FY26 goals and operating standards'],
  ];

  return (
    <div className="mx-2 mt-3 space-y-3 rounded-lg border border-sidebar-border bg-sidebar-accent/35 p-3 text-sidebar-foreground group-data-[collapsible=icon]:hidden">
      <div>
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Lakebase
        </div>
        <div className="mt-1 flex items-start gap-2 text-sm">
          <StatusDot />
          <div>
            <div className="font-medium">bobabricks</div>
            <div className="text-xs leading-5 text-muted-foreground">
              Stores regional preference and demo session memory.
            </div>
          </div>
        </div>
      </div>

      <div>
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Tools
        </div>
        <div className="mt-2 space-y-2">
          {tools.map(([name, purpose]) => (
            <div key={name} className="text-sm">
              <div>
                <div className="font-medium">{name}</div>
                <div className="text-xs leading-5 text-muted-foreground">{purpose}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const demoQuestions = [
  'What tools do you have?',
  'Show average versus actual training hours for my Pacific stores and flag any stores falling behind.',
  'What are our FY26 training goals, and how does Store 104 stack up?',
  'Generate my weekly regional risk briefing.',
];

function submitDemoQuestion(question: string) {
  const send = () => {
    const textarea = document.querySelector('textarea');
    if (!(textarea instanceof HTMLTextAreaElement)) {
      window.setTimeout(send, 80);
      return;
    }

    const valueSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      'value',
    )?.set;
    valueSetter?.call(textarea, question);
    textarea.dispatchEvent(new Event('input', { bubbles: true }));
    textarea.focus();
    textarea.closest('form')?.requestSubmit();
  };

  window.setTimeout(send, 80);
}

function BobabricksDemoQuestions({ onSelect }: { onSelect: (question: string) => void }) {
  return (
    <div className="mx-2 mt-3 space-y-2 rounded-lg border border-sidebar-border bg-sidebar-accent/20 p-3 text-sidebar-foreground group-data-[collapsible=icon]:hidden">
      <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Demo questions
      </div>
      <div className="space-y-1">
        {demoQuestions.map((question) => (
          <button
            key={question}
            type="button"
            onClick={() => onSelect(question)}
            className="block w-full rounded-md px-2 py-2 text-left text-xs leading-5 text-muted-foreground hover:bg-sidebar-accent hover:text-sidebar-foreground"
          >
            {question}
          </button>
        ))}
      </div>
    </div>
  );
}

export function AppSidebar({
  user,
  preferredUsername,
}: {
  user: ClientSession['user'] | undefined;
  preferredUsername: string | null;
}) {
  const navigate = useNavigate();
  const { setOpenMobile, open, openMobile, isMobile, toggleSidebar } = useSidebar();

  const effectiveOpen = open || (isMobile && openMobile);

  return (
    <Sidebar
      collapsible="icon"
      className="group-data-[side=left]:border-r-0"
    >
      <SidebarHeader
        className={cn(
          'h-[44px] flex-row items-center gap-2 px-2 py-0',
          effectiveOpen ? 'justify-between' : 'justify-center',
        )}
      >
        {effectiveOpen && (
          <Link
            to="/"
            onClick={() => setOpenMobile(false)}
            className="flex items-center overflow-hidden px-1"
          >
            <span className="text-base font-semibold text-foreground">
              Bobabricks
            </span>
          </Link>
        )}

        <Action
          onClick={toggleSidebar}
          tooltip={effectiveOpen ? 'Collapse sidebar' : 'Expand sidebar'}
        >
          <DbIcon
            icon={effectiveOpen ? SidebarCollapseIcon : SidebarExpandIcon}
            size={16}
            color="muted"
          />
        </Action>
      </SidebarHeader>

      <div className="px-2 pt-2">
        <SidebarMenu>
          <SidebarMenuItem>
            <Tooltip>
              <TooltipTrigger asChild>
                <SidebarMenuButton
                  type="button"
                  className="h-8 p-1 md:p-2 cursor-pointer"
                  onClick={() => {
                    setOpenMobile(false);
                    navigate('/');
                  }}
                >
                  <DbIcon icon={NewChatIcon} size={16} color="default" />
                  <span className="group-data-[collapsible=icon]:hidden">
                    New chat
                  </span>
                </SidebarMenuButton>
              </TooltipTrigger>
              <TooltipContent side="right" style={{ display: open ? 'none' : 'block' }}>New chat</TooltipContent>
            </Tooltip>
          </SidebarMenuItem>
        </SidebarMenu>
      </div>

      {effectiveOpen && <BobabricksResourcePanel />}
      {effectiveOpen && (
        <BobabricksDemoQuestions
          onSelect={(question) => {
            setOpenMobile(false);
            navigate('/');
            submitDemoQuestion(question);
          }}
        />
      )}

      <SidebarContent>
        {effectiveOpen && <SidebarHistory user={user} />}
      </SidebarContent>

      <SidebarFooter>
        {user && (
          <SidebarUserNav user={user} preferredUsername={preferredUsername} />
        )}
      </SidebarFooter>
    </Sidebar>
  );
}
"""


BOBABRICKS_SUGGESTED_ACTIONS = r"""import { motion } from 'framer-motion';
import { memo } from 'react';
import type { UseChatHelpers } from '@ai-sdk/react';
import type { VisibilityType } from './visibility-selector';
import type { ChatMessage } from '@chat-template/core';
import { Suggestion } from './elements/suggestion';
import { LightbulbIcon } from '@/components/icons';
import { softNavigateToChatId } from '@/lib/navigation';
import { useAppConfig } from '@/contexts/AppConfigContext';

interface SuggestedActionsProps {
  chatId: string;
  sendMessage: UseChatHelpers<ChatMessage>['sendMessage'];
  selectedVisibilityType: VisibilityType;
}

function PureSuggestedActions({ chatId, sendMessage }: SuggestedActionsProps) {
  const { chatHistoryEnabled } = useAppConfig();
  const suggestedActions = [
    'What tools do you have?',
    'Show average versus actual training hours for my Pacific stores and flag any stores falling behind.',
    'What are our FY26 training goals, and how does Store 104 stack up?',
    'Generate my weekly regional risk briefing.',
  ];

  return (
    <div
      data-testid="suggested-actions"
      className="flex w-full flex-col"
    >
      {suggestedActions.map((suggestedAction, index) => (
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 20 }}
          transition={{ delay: 0.05 * index }}
          key={suggestedAction}
          className="border-b border-border"
        >
          <Suggestion
            suggestion={suggestedAction}
            variant="tertiary"
            onClick={(suggestion) => {
              softNavigateToChatId(chatId, chatHistoryEnabled);
              sendMessage({
                role: 'user',
                parts: [{ type: 'text', text: suggestion }],
              });
            }}
            className="h-auto w-full justify-start gap-2 rounded-none border-0 bg-transparent py-2 pl-0 text-left text-sm font-normal text-muted-foreground hover:bg-transparent hover:text-foreground"
          >
            <LightbulbIcon size={16} className="shrink-0 text-muted-foreground" aria-hidden />
            {suggestedAction}
          </Suggestion>
        </motion.div>
      ))}
    </div>
  );
}

export const SuggestedActions = memo(
  PureSuggestedActions,
  (prevProps, nextProps) => {
    if (prevProps.chatId !== nextProps.chatId) return false;
    if (prevProps.selectedVisibilityType !== nextProps.selectedVisibilityType)
      return false;

    return true;
  },
);
"""


BOBABRICKS_GREETING = r"""import { motion } from 'framer-motion';

export const Greeting = () => {
  return (
    <div
      key="overview"
      className="mx-auto flex size-full max-w-3xl flex-col justify-center px-4 mb-6 text-center"
    >
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 10 }}
        className="space-y-3"
      >
        <div className="text-2xl font-semibold md:text-3xl">🧋 Bobabricks</div>
        <div className="text-sm font-medium text-muted-foreground">Powered by Databricks</div>
        <p className="mx-auto max-w-2xl text-sm leading-6 text-muted-foreground md:text-base">
          Bobabricks is a premium boba tea company running a store operations demo on Databricks.
          This assistant helps regional leaders inspect FY26 training goals, store execution risk,
          scheduling evidence, and approval-gated follow-up tasks across Genie, StoreTime, OpsTask,
          Confluence, and Lakebase.
        </p>
      </motion.div>
    </div>
  );
};
"""


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

    def apply_bobabricks_frontend_overlay(self) -> None:
        frontend_dir = Path("e2e-chatbot-app-next")
        (frontend_dir / "client/src/components/app-sidebar.tsx").write_text(
            BOBABRICKS_APP_SIDEBAR,
            encoding="utf-8",
        )
        (frontend_dir / "client/src/components/suggested-actions.tsx").write_text(
            BOBABRICKS_SUGGESTED_ACTIONS,
            encoding="utf-8",
        )
        (frontend_dir / "client/src/components/greeting.tsx").write_text(
            BOBABRICKS_GREETING,
            encoding="utf-8",
        )
        print("Applied Bobabricks frontend overlay.")

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
                self.apply_bobabricks_frontend_overlay()
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
