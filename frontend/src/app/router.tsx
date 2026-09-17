import { createRootRoute, createRoute, createRouter, Navigate } from "@tanstack/react-router";

import { ArtworksPage } from "@/features/artworks/ArtworksPage";
import { PairPage, SetupPage } from "@/features/auth/AuthPages";
import { DevicesPage } from "@/features/devices/DevicesPage";
import { InboxPage } from "@/features/inbox/InboxPage";
import { MobileUploadPage } from "@/features/mobile/MobileUploadPage";
import { PhotosPage } from "@/features/photos/PhotosPage";
import { ComingSoon } from "@/features/placeholder/ComingSoon";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { AuthGate } from "./AuthGate";
import { Shell } from "./Shell";

const rootRoute = createRootRoute({ component: AuthGate });

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
    page("/artworks", ArtworksPage),
    page("/favorites", () => <ComingSoon titleKey="nav.favorites" phase={8} />),
    page("/collections", () => <ComingSoon titleKey="nav.collections" phase={8} />),
    page("/templates", () => <ComingSoon titleKey="nav.templates" phase={7} />),
    page("/trash", () => <ComingSoon titleKey="nav.trash" phase={8} />),
    page("/devices", DevicesPage),
    page("/settings", SettingsPage),
  ]),
  createRoute({ getParentRoute: () => rootRoute, path: "/m", component: MobileUploadPage }),
  createRoute({ getParentRoute: () => rootRoute, path: "/setup", component: SetupPage }),
  createRoute({ getParentRoute: () => rootRoute, path: "/pair", component: PairPage }),
]);

export const router = createRouter({ routeTree, defaultPreload: false });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
