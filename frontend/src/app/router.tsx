import { createRootRoute, createRoute, createRouter, Navigate } from "@tanstack/react-router";

import { EditorPage } from "@/editor/EditorPage";
import { ArtworksPage } from "@/features/artworks/ArtworksPage";
import { PairPage, SetupPage } from "@/features/auth/AuthPages";
import { CollectionsPage } from "@/features/collections/CollectionsPage";
import { DevicesPage } from "@/features/devices/DevicesPage";
import { InboxPage } from "@/features/inbox/InboxPage";
import { MobileBrowsePage } from "@/features/mobile/MobileBrowsePage";
import { MobileUploadPage } from "@/features/mobile/MobileUploadPage";
import { PhotosPage } from "@/features/photos/PhotosPage";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { TagsPage } from "@/features/tags/TagsPage";
import { TemplatesPage } from "@/features/templates/TemplatesPage";
import { TrashPage } from "@/features/trash/TrashPage";
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
    page("/photos", PhotosPage),
    page("/artworks", () => <ArtworksPage />),
    createRoute({
      getParentRoute: () => shellRoute,
      path: "/editor/$artworkId",
      component: EditorPage,
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
