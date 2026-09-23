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
  toggleCheatSheet: () => void;
}

export const useCommands = create<CommandState>((set) => ({
  commands: new Map(),
  paletteOpen: false,
  cheatSheetOpen: false,
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  setCheatSheetOpen: (cheatSheetOpen) => set({ cheatSheetOpen }),
  toggleCheatSheet: () => set((state) => ({ cheatSheetOpen: !state.cheatSheetOpen })),
}));

/**
 * Chord guard. `g c` (go to collections) and a bare `c` (add to collection) are two bindings in
 * two `tinykeys` instances, and tinykeys matches each one on its own: pressing `g` then `c` used
 * to run *both*. One capture-phase listener remembers whether the previous key started a chord,
 * and bare single-key bindings stand down for the keystroke that follows one.
 */
const CHORD_WINDOW_MS = 1000;
const chordPrefixes = new Set<string>();
let armedAt = 0;
let suppressBare = false;
let watching = false;

function watchChords() {
  if (watching || typeof window === "undefined") return;
  watching = true;
  window.addEventListener(
    "keydown",
    (event) => {
      const bare = !event.ctrlKey && !event.metaKey && !event.altKey;
      const armed = armedAt !== 0 && Date.now() - armedAt < CHORD_WINDOW_MS;
      const isPrefix = bare && chordPrefixes.has(event.key);
      suppressBare = armed && !isPrefix;
      armedAt = isPrefix ? Date.now() : 0;
    },
    true,
  );
}

/** A shortcut that is one key with no modifier — the kind a chord's second key collides with. */
function isBareKey(shortcut: string): boolean {
  return !shortcut.includes(" ") && !shortcut.includes("+");
}

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
    watchChords();
    for (const command of latest.current) {
      const [prefix, ...rest] = (command.shortcut ?? "").split(" ");
      if (prefix && rest.length > 0) chordPrefixes.add(prefix);
    }
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
      const bare = isBareKey(command.shortcut);
      bindings[command.shortcut] = (event) => {
        if (!command.allowInInputs && isTyping(event)) return;
        if (bare && suppressBare) return; // the second key of a chord, not a shortcut of its own
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
