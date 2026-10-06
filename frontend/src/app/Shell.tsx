import { Link, Outlet, useNavigate } from "@tanstack/react-router";
import {
  Activity,
  Archive,
  ChevronDown,
  ChevronRight,
  Frame,
  Heart,
  Images,
  Inbox,
  Keyboard,
  Layers,
  LayoutTemplate,
  MonitorPlay,
  MonitorSmartphone,
  Search,
  Settings,
  Smartphone,
  TagsIcon,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { onServerEvent } from "@/api/events";
import { useCollectionItems, useCollections, useJobs, useLibraryStats } from "@/api/queries";
import { CollectionTree } from "@/features/collections/CollectionTree";
import { PushTray } from "@/features/display/PushTray";
import { GlobalDropZone } from "@/features/upload/DropZone";
import { useFilePickers } from "@/features/upload/useFilePickers";
import { LocalSendRequestDialog } from "@/features/localsend/LocalSendRequestDialog";
import { UploadTray } from "@/features/upload/UploadTray";
import { mirrorLocalSendTransfers } from "@/features/upload/uploadStore";
import { cn } from "@/shared/cn";
import { toast } from "@/shared/toast";
import { Button } from "@/shared/ui/Button";
import { Badge, Kbd } from "@/shared/ui/Misc";
import { Toaster } from "@/shared/ui/Toaster";

import { CheatSheet, CommandPalette } from "./CommandPalette";
import { formatShortcut, useCommands, useRegisterCommands, type Command } from "./commands";
import { useTheme } from "./theme";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  count?: number;
  /** A count that is bad news (failed jobs) reads as bad news. */
  countTone?: "accent" | "danger";
}

function NavLink({ item }: { item: NavItem }) {
  return (
    <Link
      to={item.to}
      className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-muted transition hover:bg-panel-2 hover:text-text"
      activeProps={{ className: "bg-panel-2 !text-text" }}
    >
      {item.icon}
      <span className="flex-1 truncate">{item.label}</span>
      {item.count !== undefined && item.count > 0 && (
        <span
          className={cn(
            "rounded-full px-1.5 text-[11px] font-semibold",
            item.countTone === "danger" ? "bg-danger/20 text-danger" : "bg-accent/20 text-accent",
          )}
        >
          {item.count}
        </span>
      )}
    </Link>
  );
}

const COLLECTIONS_OPEN_KEY = "tf.sidebar.collections";

/** Whether the sidebar's collection tree is unfolded: a per-browser convenience, open by default. */
function useCollectionsOpen(): [boolean, () => void] {
  const [open, setOpen] = useState(() => {
    try {
      return localStorage.getItem(COLLECTIONS_OPEN_KEY) !== "closed";
    } catch {
      return true; /* storage unavailable */
    }
  });
  const toggle = () =>
    setOpen((current) => {
      try {
        localStorage.setItem(COLLECTIONS_OPEN_KEY, current ? "closed" : "open");
      } catch {
        /* storage unavailable */
      }
      return !current;
    });
  return [open, toggle];
}

/**
 * The Collections link, with the collection tree right under it: dropping artworks on a row files
 * them. A long tree would push everything else out of the sidebar, so it folds away.
 */
function SidebarCollections({ item }: { item: NavItem }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const collections = useCollections();
  const items = useCollectionItems();
  const [open, toggle] = useCollectionsOpen();
  const rows = collections.data ?? [];
  if (rows.length === 0) return <NavLink item={item} />;
  return (
    <>
      <div className="flex items-center gap-0.5">
        <div className="min-w-0 flex-1">
          <NavLink item={item} />
        </div>
        <button
          type="button"
          onClick={toggle}
          aria-expanded={open}
          aria-controls="sidebar-collections"
          aria-label={open ? t("nav.hideCollections") : t("nav.showCollections")}
          title={open ? t("nav.hideCollections") : t("nav.showCollections")}
          className="rounded-md p-1.5 text-muted hover:bg-panel-2 hover:text-text"
        >
          {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
      </div>
      {open && (
        <div id="sidebar-collections" className="pt-1 pl-1.5">
          {/* A row opens *that* collection, not the page: the id travels in the URL (user feedback). */}
          <CollectionTree
            rows={rows}
            selectedId={null}
            onSelect={(id) => void navigate({ to: "/collections", search: { id } })}
            onDropArtworks={(id, artworkIds) => items.add.mutate({ id, artwork_ids: artworkIds })}
          />
        </div>
      )}
    </>
  );
}

export function Shell() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const stats = useLibraryStats();
  const jobs = useJobs();
  useEffect(() => mirrorLocalSendTransfers(), []);
  // A job that failed off-screen is said once, with a way to the activity centre (phase 11 §14.3).
  useEffect(
    () =>
      onServerEvent("job.failed", (event) =>
        // A coded failure gets the title *and* its own sentence; an uncoded one would otherwise
        // print the same words twice, so it is left as the title alone.
        toast.problem(event.code ?? undefined, "activity.jobFailed", {
          label: "activity.view",
          run: () => void navigate({ to: "/activity" }),
        }),
      ),
    [navigate],
  );
  const { openFiles, openFolder } = useFilePickers();
  const toggleTheme = useTheme((s) => s.toggle);
  const setPaletteOpen = useCommands((s) => s.setPaletteOpen);
  const setCheatSheetOpen = useCommands((s) => s.setCheatSheetOpen);
  const toggleCheatSheet = useCommands((s) => s.toggleCheatSheet);

  const commands = useMemo<Command[]>(() => {
    const go = (to: string) => () => void navigate({ to });
    return [
      {
        id: "palette.open",
        label: "palette.title",
        group: "commands.groups.general",
        shortcut: "$mod+k",
        allowInInputs: true,
        run: () => setPaletteOpen(true),
      },
      {
        id: "shortcuts.open",
        label: "shortcuts.title",
        group: "commands.groups.general",
        shortcut: "Shift+?",
        // Toggles: `?` opens the cheat sheet and closes it again (it stays bound while it shows).
        run: toggleCheatSheet,
      },
      {
        id: "theme.toggle",
        label: "commands.toggleTheme",
        group: "commands.groups.general",
        shortcut: "Shift+T",
        run: toggleTheme,
      },
      {
        id: "upload.files",
        label: "commands.uploadFiles",
        group: "commands.groups.library",
        shortcut: "u",
        run: openFiles,
      },
      {
        id: "upload.folder",
        label: "commands.uploadFolder",
        group: "commands.groups.library",
        shortcut: "Shift+U",
        run: openFolder,
      },
      {
        id: "go.inbox",
        label: "commands.goInbox",
        group: "commands.groups.navigation",
        shortcut: "g i",
        run: go("/inbox"),
      },
      {
        id: "go.photos",
        label: "commands.goPhotos",
        group: "commands.groups.navigation",
        shortcut: "g p",
        run: go("/photos"),
      },
      {
        id: "go.artworks",
        label: "commands.goArtworks",
        group: "commands.groups.navigation",
        shortcut: "g a",
        run: go("/artworks"),
      },
      {
        id: "go.display",
        label: "commands.goDisplay",
        group: "commands.groups.navigation",
        run: go("/display"),
      },
      {
        id: "go.devices",
        label: "commands.goDevices",
        group: "commands.groups.navigation",
        shortcut: "g d",
        run: go("/devices"),
      },
      {
        id: "go.settings",
        label: "commands.goSettings",
        group: "commands.groups.navigation",
        shortcut: "g s",
        run: go("/settings"),
      },
      {
        id: "go.collections",
        label: "commands.goCollections",
        group: "commands.groups.navigation",
        shortcut: "g c",
        run: go("/collections"),
      },
      {
        id: "go.favorites",
        label: "commands.goFavorites",
        group: "commands.groups.navigation",
        shortcut: "g f",
        run: go("/favorites"),
      },
      {
        id: "go.tags",
        label: "commands.goTags",
        group: "commands.groups.navigation",
        shortcut: "g t",
        run: go("/tags"),
      },
      {
        id: "go.activity",
        label: "commands.goActivity",
        group: "commands.groups.navigation",
        run: go("/activity"),
      },
      {
        id: "go.trash",
        label: "commands.goTrash",
        group: "commands.groups.navigation",
        run: go("/trash"),
      },
      {
        id: "go.backup",
        label: "commands.goBackup",
        group: "commands.groups.navigation",
        shortcut: "g b",
        run: go("/backup"),
      },
      {
        id: "go.mobile",
        label: "commands.goMobile",
        group: "commands.groups.navigation",
        run: go("/m"),
      },
    ];
  }, [navigate, openFiles, openFolder, setPaletteOpen, toggleCheatSheet, toggleTheme]);
  useRegisterCommands(commands);

  const library: NavItem[] = [
    { to: "/inbox", label: t("nav.inbox"), icon: <Inbox size={16} />, count: stats.data?.inbox },
    { to: "/artworks", label: t("nav.artworks"), icon: <Frame size={16} /> },
    { to: "/photos", label: t("nav.photos"), icon: <Images size={16} /> },
    { to: "/favorites", label: t("nav.favorites"), icon: <Heart size={16} /> },
  ];
  const collectionsItem: NavItem = {
    to: "/collections",
    label: t("nav.collections"),
    icon: <Layers size={16} />,
  };
  const manage: NavItem[] = [
    { to: "/tags", label: t("nav.tags"), icon: <TagsIcon size={16} /> },
    { to: "/templates", label: t("nav.templates"), icon: <LayoutTemplate size={16} /> },
    { to: "/trash", label: t("nav.trash"), icon: <Trash2 size={16} /> },
    {
      to: "/activity",
      label: t("nav.activity"),
      icon: <Activity size={16} />,
      count: jobs.data?.failed,
      countTone: "danger",
    },
    { to: "/backup", label: t("nav.backup"), icon: <Archive size={16} /> },
    { to: "/display", label: t("nav.display"), icon: <MonitorPlay size={16} /> },
    { to: "/devices", label: t("nav.devices"), icon: <MonitorSmartphone size={16} /> },
    { to: "/settings", label: t("nav.settings"), icon: <Settings size={16} /> },
  ];

  return (
    <div className="flex h-full">
      {/* First tab stop: past a sidebar of ~20 links, straight to the page (WCAG 2.4.1). */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-panel focus:px-3 focus:py-2 focus:text-sm focus:shadow-lg"
      >
        {t("nav.skipToContent")}
      </a>
      <nav
        className="flex w-56 shrink-0 flex-col gap-4 border-r border-border bg-panel px-2.5 py-3"
        aria-label={t("nav.label")}
      >
        <div className="flex items-center gap-2 px-2 text-sm font-semibold tracking-wide">
          <Frame size={18} className="text-accent" /> Frame It
          <Badge tone="accent" title={t("nav.betaHint")}>
            {t("nav.beta")}
          </Badge>
        </div>
        <button
          onClick={() => setPaletteOpen(true)}
          className="flex items-center gap-2 rounded-md border border-border bg-bg px-2.5 py-1.5 text-left text-sm text-muted hover:text-text"
        >
          <Search size={14} />
          <span className="flex-1">{t("palette.search")}</span>
          <Kbd>{formatShortcut("$mod+k")}</Kbd>
        </button>
        <Button variant="primary" onClick={openFiles} className="w-full">
          <Upload size={16} /> {t("upload.addPhotos")}
        </Button>
        <div className="min-h-0 space-y-0.5 overflow-y-auto">
          {library.map((item) => (
            <NavLink key={item.to} item={item} />
          ))}
          <SidebarCollections item={collectionsItem} />
        </div>
        <div className="space-y-0.5">
          <div className="px-2.5 pb-1 text-[11px] text-muted uppercase">{t("nav.manage")}</div>
          {manage.map((item) => (
            <NavLink key={item.to} item={item} />
          ))}
        </div>
        <div className="mt-auto space-y-3">
          {/* A push to the TV takes minutes: it shows here, whatever page is open. */}
          <PushTray />
          <div className="space-y-0.5">
            <NavLink item={{ to: "/m", label: t("nav.mobile"), icon: <Smartphone size={16} /> }} />
            <button
              onClick={() => setCheatSheetOpen(true)}
              className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-muted hover:bg-panel-2 hover:text-text"
            >
              <Keyboard size={16} /> {t("shortcuts.title")}
            </button>
          </div>
        </div>
      </nav>
      <main id="main" className="min-w-0 flex-1 overflow-hidden">
        <Outlet />
      </main>
      <Toaster />
      <UploadTray />
      <GlobalDropZone />
      <CommandPalette />
      <CheatSheet />
      <LocalSendRequestDialog />
    </div>
  );
}
