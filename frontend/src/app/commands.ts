/**
 * Central command registry: every user action with a keyboard shortcut is registered here so the
 * command palette (Ctrl/Cmd+K) and the cheat sheet (?) list them. Features register their commands
 * with `useRegisterCommands` while mounted.
 */
import { useEffect, useLayoutEffect, useRef } from "react";
import { tinykeys } from "tinykeys";
import { create } from "zustand";

export interface Command {
  id: string;
  /** i18n key of the label. */
  label: string;
  /** i18n key of the group. */
  group: string;
  /** tinykeys binding, e.g. "$mod+k", "g i", "Shift+?". */
  shortcut?: string;
  run: () => void;
  /** Whether the shortcut also fires while typing in an input. */
  allowInInputs?: boolean;
}

interface CommandState {
  commands: Map<string, Command>;
  paletteOpen: boolean;
  cheatSheetOpen: boolean;
  setPaletteOpen: (open: boolean) => void;
  setCheatSheetOpen: (open: boolean) => void;
}

export const useCommands = create<CommandState>((set) => ({
  commands: new Map(),
  paletteOpen: false,
  cheatSheetOpen: false,
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  setCheatSheetOpen: (cheatSheetOpen) => set({ cheatSheetOpen }),
}));

function isTyping(event: KeyboardEvent): boolean {
  const target = event.target as HTMLElement | null;
  if (!target) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/**
 * Register commands while the calling component is mounted. Registration only changes when the
 * set of ids/shortcuts changes; `run` always calls the latest callback (no re-render loops).
 */
export function useRegisterCommands(commands: Command[]) {
  const latest = useRef(commands);
  useLayoutEffect(() => {
    latest.current = commands;
  });
  const signature = commands
    .map((c) => `${c.id}|${c.shortcut ?? ""}|${c.label}|${c.group}`)
    .join(";");

  useEffect(() => {
    const invoke = (id: string) => latest.current.find((c) => c.id === id)?.run();
    const stable: Command[] = latest.current.map((command) => ({
      ...command,
      run: () => invoke(command.id),
    }));
    const registry = new Map(useCommands.getState().commands);
    stable.forEach((command) => registry.set(command.id, command));
    useCommands.setState({ commands: registry });

    const bindings: Record<string, (event: KeyboardEvent) => void> = {};
    for (const command of stable) {
      if (!command.shortcut) continue;
      bindings[command.shortcut] = (event) => {
        if (!command.allowInInputs && isTyping(event)) return;
        event.preventDefault();
        command.run();
      };
    }
    const unsubscribe = tinykeys(window, bindings);
    return () => {
      unsubscribe();
      const next = new Map(useCommands.getState().commands);
      stable.forEach((command) => {
        if (next.get(command.id) === command) next.delete(command.id);
      });
      useCommands.setState({ commands: next });
    };
  }, [signature]);
}

/** Human-readable shortcut, e.g. "$mod+k" → "Ctrl K" / "⌘ K". */
export function formatShortcut(shortcut: string): string {
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
  return shortcut
    .split(" ")
    .map((chord) =>
      chord
        .replace("$mod", isMac ? "⌘" : "Ctrl")
        .replace("Shift", "⇧")
        .split("+")
        .join(" "),
    )
    .join(" › ");
}
