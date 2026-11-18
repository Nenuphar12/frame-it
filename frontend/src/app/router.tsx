import {
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
  Navigate,
} from "@tanstack/react-router";

import { ActivityPage } from "@/features/activity/ActivityPage";
import { BackupPage } from "@/features/archive/BackupPage";
import { ArtworksPage, type ArtworksSearch } from "@/features/artworks/ArtworksPage";
import { PairPage, SetupPage } from "@/features/auth/AuthPages";
import { CollectionsPage } from "@/features/collections/CollectionsPage";
import { DevicesPage } from "@/features/devices/DevicesPage";
import { DisplayPage } from "@/features/display/DisplayPage";
import { InboxPage } from "@/features/inbox/InboxPage";
import { MobileBrowsePage } from "@/features/mobile/MobileBrowsePage";
import { MobileUploadPage } from "@/features/mobile/MobileUploadPage";
import { PhotosPage, type PhotosSearch } from "@/features/photos/PhotosPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { TagsPage } from "@/features/tags/TagsPage";
import { TemplatesPage } from "@/features/templates/TemplatesPage";
import { TrashPage } from "@/features/trash/TrashPage";
import { isPeriod } from "@/shared/period";
import { AuthGate } from "./AuthGate";
import { Shell } from "./Shell";

const rootRoute = createRootRoute({ component: AuthGate });

/** Review queue carried in the URL so an editing session survives a reload (§11.1). */
interface EditorSearch {
  queue?: string;
}

/** Which collection is open, so the sidebar can link straight to one and a reload keeps it. */
interface CollectionsSearch {
  id?: string;
}

const NEAR_LINK = /^-?\d+(\.\d+)?,-?\d+(\.\d+)?,\d+(\.\d+)?$/;

/**
 * A search value as text. The router parses each value as JSON first, so a hand-typed
 * `?taken=2024` arrives as a number (its own links quote such strings: `?taken=%222024%22`).
 */
function text(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return undefined;
}

/** `taken` = a year or a month (the Timeline's links); anything else is dropped, not an error. */
function takenFrom(search: Record<string, unknown>): { taken?: string } {
  const taken = text(search.taken);
  return isPeriod(taken) ? { taken } : {};
}

const shellRoute = createRoute({ getParentRoute: () => rootRoute, id: "shell", component: Shell });

const page = (path: string, component: () => React.ReactNode) =>
  createRoute({ getParentRoute: () => shellRoute, path, component });

const routeTree = rootRoute.addChildren([
  shellRoute.addChildren([
    createRoute({
      getParentRoute: () => shellRoute,
      path: "/",
      component: () => <Navigate to="/inbox" replace />,
    }),
    page("/inbox", InboxPage),
    createRoute({
      getParentRoute: () => shellRoute,
      path: "/photos",
      component: PhotosPage,
      // The Timeline's links (`taken`) and the Places view's (a row: `""` is its "Unknown").
      validateSearch: (search: Record<string, unknown>): PhotosSearch => {
        const level = (key: "place_country" | "place_admin1" | "place_name") => {
          const value = text(search[key]);
          return value === undefined ? {} : { [key]: value };
        };
        return {
          ...takenFrom(search),
          ...level("place_country"),
          ...level("place_admin1"),
          ...level("place_name"),
        };
      },
    }),
    createRoute({
      getParentRoute: () => shellRoute,
      path: "/artworks",
      component: () => <ArtworksPage />,
      validateSearch: (search: Record<string, unknown>): ArtworksSearch => ({
        ...(typeof search.place === "string" && search.place ? { place: search.place } : {}),
        ...(typeof search.tag === "string" && search.tag ? { tag: search.tag } : {}),
        // `near=lat,lon,km` — three numbers or nothing (a hand-edited link must not break the grid).
        ...(typeof search.near === "string" && NEAR_LINK.test(search.near)
          ? { near: search.near }
          : {}),
        ...(typeof search.label === "string" && search.label ? { label: search.label } : {}),
        ...takenFrom(search),
      }),
    }),
    createRoute({
      getParentRoute: () => shellRoute,
      path: "/editor/$artworkId",
      // Its own chunk: the editor is half the bundle (Konva and its renderer), and phones on
      // `/m` never open it. A chunk gone with a rebuild reloads the page once (TanStack's own).
      component: lazyRouteComponent(() => import("@/editor/EditorPage"), "EditorPage"),
      validateSearch: (search: Record<string, unknown>): EditorSearch =>
        typeof search.queue === "string" ? { queue: search.queue } : {},
    }),
    page("/favorites", () => <ArtworksPage favoritesOnly />),
    createRoute({
      getParentRoute: () => shellRoute,
      path: "/collections",
      component: CollectionsPage,
      validateSearch: (search: Record<string, unknown>): CollectionsSearch =>
        typeof search.id === "string" ? { id: search.id } : {},
    }),
    page("/tags", TagsPage),
    page("/templates", TemplatesPage),
    page("/trash", TrashPage),
    page("/activity", ActivityPage),
    page("/backup", BackupPage),
    page("/display", DisplayPage),
    page("/devices", DevicesPage),
    page("/settings", SettingsPage),
  ]),
  createRoute({ getParentRoute: () => rootRoute, path: "/m", component: MobileUploadPage }),
  createRoute({ getParentRoute: () => rootRoute, path: "/m/browse", component: MobileBrowsePage }),
  createRoute({ getParentRoute: () => rootRoute, path: "/setup", component: SetupPage }),
  createRoute({ getParentRoute: () => rootRoute, path: "/pair", component: PairPage }),
]);

export const router = createRouter({ routeTree, defaultPreload: false });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
