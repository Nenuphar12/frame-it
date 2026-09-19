import { Link, Outlet, useNavigate } from "@tanstack/react-router";
import {
  Frame,
  Heart,
  Images,
  Inbox,
  Keyboard,
  Layers,
  LayoutTemplate,
  MonitorSmartphone,
  Search,
  Settings,
  Smartphone,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useMemo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { useLibraryStats } from "@/api/queries";
import { GlobalDropZone } from "@/features/upload/DropZone";
import { useFilePickers } from "@/features/upload/useFilePickers";
import { LocalSendRequestDialog } from "@/features/localsend/LocalSendRequestDialog";
import { UploadTray } from "@/features/upload/UploadTray";
import { mirrorLocalSendTransfers } from "@/features/upload/uploadStore";
import { Button } from "@/shared/ui/Button";
import { Kbd } from "@/shared/ui/Misc";

import { CheatSheet, CommandPalette } from "./CommandPalette";
import { formatShortcut, useCommands, useRegisterCommands, type Command } from "./commands";
import { useTheme } from "./theme";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  count?: number;
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
        <span className="rounded-full bg-accent/20 px-1.5 text-[11px] font-semibold text-accent">
          {item.count}
        </span>
      )}
    </Link>
  );
}

export function Shell() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const stats = useLibraryStats();
  useEffect(() => mirrorLocalSendTransfers(), []);
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
    { to: "/collections", label: t("nav.collections"), icon: <Layers size={16} /> },
  ];
  const manage: NavItem[] = [
    { to: "/templates", label: t("nav.templates"), icon: <LayoutTemplate size={16} /> },
    { to: "/trash", label: t("nav.trash"), icon: <Trash2 size={16} /> },
    { to: "/devices", label: t("nav.devices"), icon: <MonitorSmartphone size={16} /> },
    { to: "/settings", label: t("nav.settings"), icon: <Settings size={16} /> },
  ];

  return (
    <div className="flex h-full">
      <nav
        className="flex w-56 shrink-0 flex-col gap-4 border-r border-border bg-panel px-2.5 py-3"
        aria-label={t("nav.label")}
      >
        <div className="flex items-center gap-2 px-2 text-sm font-semibold tracking-wide">
          <Frame size={18} className="text-accent" /> the_frame_v2
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
        <div className="space-y-0.5">
          {library.map((item) => (
            <NavLink key={item.to} item={item} />
          ))}
        </div>
        <div className="space-y-0.5">
          <div className="px-2.5 pb-1 text-[11px] text-muted uppercase">{t("nav.manage")}</div>
          {manage.map((item) => (
            <NavLink key={item.to} item={item} />
          ))}
        </div>
        <div className="mt-auto space-y-0.5">
          <NavLink item={{ to: "/m", label: t("nav.mobile"), icon: <Smartphone size={16} /> }} />
          <button
            onClick={() => setCheatSheetOpen(true)}
            className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-muted hover:bg-panel-2 hover:text-text"
          >
            <Keyboard size={16} /> {t("shortcuts.title")}
          </button>
        </div>
      </nav>
      <main className="min-w-0 flex-1 overflow-hidden">
        <Outlet />
      </main>
      <UploadTray />
      <GlobalDropZone />
      <CommandPalette />
      <CheatSheet />
      <LocalSendRequestDialog />
    </div>
  );
}
