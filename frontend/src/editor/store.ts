// Editor state: the working document, undo/redo and autosave. Spec: docs/PLAN.md §11.1.
//
// The document lives outside React (like the upload queue) so that a drag can produce dozens of
// updates per second without re-rendering anything but the canvas. Every edit goes through
// `edit()`, which records Immer patches for undo/redo and schedules an autosave.
import { applyPatches, enablePatches, produceWithPatches, type Patch } from "immer";
import { create } from "zustand";

import { ApiError, api, unwrap, type Artwork } from "@/api/client";
import {
  normalizeDocument,
  sameDocument,
  toApiDocument,
  type EditorDocument,
} from "@/editor/core/document.ts";
import type { PhotoSizes } from "@/editor/operations";

enablePatches();

export const AUTOSAVE_MS = 800;
export const MAX_UNDO = 200;
const GROUP_MS = 900;

export type SaveState = "idle" | "dirty" | "saving" | "saved" | "error";
export type Tool = "select" | "crop";

interface Step {
  patches: Patch[];
  inverse: Patch[];
  /** Consecutive edits sharing a group are merged into one undo step (a drag = one step). */
  group: string | null;
  at: number;
}

export interface Conflict {
  /** The document currently stored on the server. */
  server: EditorDocument;
  version: number;
}

interface EditorState {
  artworkId: string | null;
  doc: EditorDocument | null;
  /** Last document known to be stored on the server (autosave target). */
  saved: EditorDocument | null;
  version: number;
  sizes: PhotoSizes;
  selectedSlotId: string | null;
  tool: Tool;
  undo: Step[];
  redo: Step[];
  saveState: SaveState;
  saveError: string | null;
  conflict: Conflict | null;
  /** Snapshot taken when the editor opened ("Revert to when opened"). */
  openedSnapshotId: string | null;
}

const initial: EditorState = {
  artworkId: null,
  doc: null,
  saved: null,
  version: 0,
  sizes: {},
  selectedSlotId: null,
  tool: "select",
  undo: [],
  redo: [],
  saveState: "idle",
  saveError: null,
  conflict: null,
  openedSnapshotId: null,
};

export const useEditor = create<EditorState>(() => initial);

let saveTimer: ReturnType<typeof setTimeout> | null = null;
let saving = false;

// ---- loading -----------------------------------------------------------------------------------
/** Start (or re-target) the editor on an artwork; keeps unsaved edits of the same artwork. */
export function openArtwork(artwork: Artwork, sizes: PhotoSizes): void {
  const state = useEditor.getState();
  if (state.artworkId === artwork.id) {
    // Only write when a size is actually new: a fresh object on every call would re-render the
    // whole editor in a loop (the sizes come from a query that re-runs on every render).
    const added = Object.keys(sizes).filter((id) => !state.sizes[id]);
    if (added.length > 0) useEditor.setState({ sizes: { ...state.sizes, ...sizes } });
    return;
  }
  cancelSave();
  const doc = normalizeDocument(artwork.document);
  useEditor.setState({
    ...initial,
    artworkId: artwork.id,
    doc,
    saved: doc,
    version: artwork.document_version,
    sizes,
    selectedSlotId: doc.slots[0]?.id ?? null,
  });
  void createOpenedSnapshot(artwork.id);
}

export function closeEditor(): void {
  cancelSave();
  useEditor.setState(initial);
}

async function createOpenedSnapshot(artworkId: string): Promise<void> {
  try {
    const snapshot = await unwrap(
      api.POST("/api/v1/artworks/{artwork_id}/snapshots", {
        params: { path: { artwork_id: artworkId } },
        body: { reason: "opened" },
      }),
    );
    if (useEditor.getState().artworkId === artworkId) {
      useEditor.setState({ openedSnapshotId: snapshot.id });
    }
  } catch {
    // A missing snapshot only costs the "revert to when opened" action.
  }
}

// ---- editing -----------------------------------------------------------------------------------
/**
 * Apply a mutation to the working document. `group` merges quick successive edits (a slider drag,
 * a crop pan) into a single undo step.
 */
export function edit(recipe: (doc: EditorDocument) => void, group: string | null = null): void {
  const state = useEditor.getState();
  if (!state.doc) return;
  const [next, patches, inverse] = produceWithPatches(state.doc, recipe);
  if (patches.length === 0) return;
  const now = Date.now();
  const last = state.undo[state.undo.length - 1];
  const merge = group !== null && last?.group === group && now - last.at < GROUP_MS;
  const step: Step = merge
    ? {
        patches: [...last.patches, ...patches],
        inverse: [...inverse, ...last.inverse],
        group,
        at: now,
      }
    : { patches, inverse, group, at: now };
  const undo = merge ? [...state.undo.slice(0, -1), step] : [...state.undo, step];
  useEditor.setState({
    doc: next,
    undo: undo.slice(-MAX_UNDO),
    redo: [],
    saveState: "dirty",
  });
  scheduleSave();
}

/** Replace the whole document (snapshot restore, conflict resolution) as one undo step. */
export function replaceDocument(document: EditorDocument): void {
  edit((doc) => {
    doc.canvas = document.canvas;
    doc.mat = document.mat;
    doc.placement = document.placement;
    doc.margins = document.margins;
    doc.slots = document.slots;
    doc.captions = document.captions;
  });
}

export function undo(): void {
  const state = useEditor.getState();
  const step = state.undo[state.undo.length - 1];
  if (!step || !state.doc) return;
  useEditor.setState({
    doc: applyPatches(state.doc, step.inverse),
    undo: state.undo.slice(0, -1),
    redo: [...state.redo, step],
    saveState: "dirty",
  });
  scheduleSave();
}

export function redo(): void {
  const state = useEditor.getState();
  const step = state.redo[state.redo.length - 1];
  if (!step || !state.doc) return;
  useEditor.setState({
    doc: applyPatches(state.doc, step.patches),
    undo: [...state.undo, step],
    redo: state.redo.slice(0, -1),
    saveState: "dirty",
  });
  scheduleSave();
}

export function select(slotId: string | null): void {
  useEditor.setState({ selectedSlotId: slotId });
}

export function setTool(tool: Tool): void {
  useEditor.setState({ tool });
}

// ---- autosave ----------------------------------------------------------------------------------
function cancelSave(): void {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = null;
}

function scheduleSave(): void {
  cancelSave();
  saveTimer = setTimeout(() => void save(), AUTOSAVE_MS);
}

/** Save now (also called before leaving the editor, so at most `AUTOSAVE_MS` can be lost). */
export async function save(): Promise<boolean> {
  cancelSave();
  const state = useEditor.getState();
  if (!state.artworkId || !state.doc || state.conflict) return false;
  if (state.saved && sameDocument(state.doc, state.saved)) {
    useEditor.setState({ saveState: "saved" });
    return true;
  }
  if (saving) {
    scheduleSave();
    return false;
  }
  saving = true;
  const pending = state.doc;
  useEditor.setState({ saveState: "saving", saveError: null });
  try {
    const artwork = await unwrap(
      api.PUT("/api/v1/artworks/{artwork_id}/document", {
        params: { path: { artwork_id: state.artworkId } },
        body: toApiDocument(pending),
        headers: { "If-Match": `"${state.version}"` },
      }),
    );
    const current = useEditor.getState();
    useEditor.setState({
      version: artwork.document_version,
      saved: pending,
      saveState: current.doc && sameDocument(current.doc, pending) ? "saved" : "dirty",
    });
    if (current.doc && !sameDocument(current.doc, pending)) scheduleSave();
    return true;
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      await loadConflict();
    } else {
      useEditor.setState({
        saveState: "error",
        saveError: error instanceof ApiError ? error.code : "unknown",
      });
    }
    return false;
  } finally {
    saving = false;
  }
}

/** 409: fetch what the server has so the user can choose (keep mine / take theirs). */
async function loadConflict(): Promise<void> {
  const { artworkId } = useEditor.getState();
  if (!artworkId) return;
  try {
    const artwork = await unwrap(
      api.GET("/api/v1/artworks/{artwork_id}", { params: { path: { artwork_id: artworkId } } }),
    );
    useEditor.setState({
      saveState: "error",
      saveError: "version_conflict",
      conflict: {
        server: normalizeDocument(artwork.document),
        version: artwork.document_version,
      },
    });
  } catch {
    useEditor.setState({ saveState: "error", saveError: "version_conflict" });
  }
}

/** Resolve a save conflict: keep the local document (overwrite) or take the server's. */
export function resolveConflict(choice: "mine" | "theirs"): void {
  const state = useEditor.getState();
  if (!state.conflict) return;
  const { server, version } = state.conflict;
  if (choice === "theirs") {
    useEditor.setState({
      conflict: null,
      doc: server,
      saved: server,
      version,
      undo: [],
      redo: [],
      saveState: "saved",
      saveError: null,
    });
    return;
  }
  useEditor.setState({ conflict: null, version, saved: null, saveState: "dirty" });
  void save();
}

// ---- selectors ---------------------------------------------------------------------------------
export const selectedSlot = (state: EditorState) =>
  state.doc?.slots.find((slot) => slot.id === state.selectedSlotId) ?? null;

export const canUndo = (state: EditorState) => state.undo.length > 0;
export const canRedo = (state: EditorState) => state.redo.length > 0;
