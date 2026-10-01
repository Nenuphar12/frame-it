# Organization — tags, collections, filters, search, trash (Phase 9)

> Spec for `docs/PLAN.md` §14 Phase 9. Data model: `docs/data-model.md` (§5.1 tables, §5.2 the
> filter AST). Implemented 2026-09-23.

The library is one flat pile of artworks until something groups it. Phase 9 adds the four ways to
do that — **tags**, **collections**, **filters** and **search** — plus the one way to take things
out of it safely: the **trash**.

One idea runs through all of it: *a filter is a value*. The chips in the filter bar, a smart
collection's stored definition and what `POST /artworks/query` compiles are the same object
(`domain/filters.py`), so "save this view as a collection" is a copy, not a translation.

---

## 1. Tags

Case-insensitive-unique names (`tags`), attached to **photos** and to **artworks** through two link
tables, each optionally in one **category**. `services/tags.py` owns them.

| Action | Rule |
|---|---|
| Create | `POST /tags` returns the existing tag when the name is taken (the picker relies on it); a `category_id` only applies to a *new* tag — an existing one keeps its own |
| Rename | 409 `tag_exists` when another tag has that name — *merge* is the way out, never a silent join |
| Recolour | `#rrggbb` / `#rrggbbaa`, or `""` to clear (the tag then shows its category's colour) |
| Re-categorise | `PATCH /tags/{id}` `category_id` (absent = unchanged, `null` = Other); many at once with `POST /tags/categorize` |
| Merge | every link of the sources moves to the target, a link that would duplicate collapses, the sources are deleted |
| Delete | links go, nothing else does: a tag is never a container |
| Clean up | `GET /tags/unused` / `POST /tags/delete-unused`: tags attached to nothing — a link from a *trashed* photo or artwork counts as a use, so restoring it never finds its tag gone |

### 1.1 An artwork carries its photos' tags

An artwork's **effective** tags are its own **plus the tags of the photos it uses** (live photos:
a trashed one stops lending its tags). They are *read*, never copied: tagging a photo later tags
every artwork made of it, and removing a photo from an artwork removes what it lent. It is the
reading `taken_at` and `place` already have — an artwork shows Alice when one of its photos does.

- **Filters and smart collections** — the `tag` clause (`has_any`, `has_all`, `none`) matches
  own *or* inherited tags (`services/library._carries`). One compiler, so the filter bar, smart
  collections, `nested_count` and `POST /filters/validate` all follow.
- **Search** — an artwork's FTS text holds its own tag names *and* its photos'. Every write that
  changes a photo's tags re-indexes the artworks using it (`search.index_artworks_using`: single
  and bulk tagging, rename / merge / delete, ingest, a duplicate upload, an archive import). The
  index carries a version (`search.INDEX_VERSION`, in a marker row), and startup rebuilds an index
  written under older rules once.
- **API** — an artwork's `tags` are its own (removable from it); `inherited_tags` are its photos'
  that it does not also own. The UI shows the latter apart — dashed, *from its photos*, never
  removable on the artwork, exactly like smart-collection membership.
- **Counts** — `artwork_count` is what the filter returns (own or inherited, distinct artworks);
  `own_artwork_count` is what deleting the tag detaches from artworks directly. The delete dialog
  says both: an artwork that only carried the tag through a photo loses it too.

Tags that are about the *artwork* rather than its content ("to print", "living room") are simply
its own tags.

### 1.2 Bulk tagging

`POST /photos/tags` and `POST /artworks/tags` take `{ids, add, remove}` and are **additive**: only
the tags named move, so tagging fifty photos that carry different tags never replaces anything.
422 `unknown_tag`, or `tag_conflict` when one tag is both added and removed. On artworks `remove`
only reaches their own tags — an inherited one belongs to a photo and is removed there.

The UI is one **tag menu** (`features/tags/TagMenu.tsx`, key `t`) on every selection — Photos,
Inbox, Artworks, Favorites, a collection — and on a batch that just arrived (*Tag these N
photos…* in the upload tray, duplicates included). Each row says whether **all**, **some** or
**none** of the selection carry the tag; a click adds it to all of them, or removes it from all of
them when they all have it. It can create a tag on the spot.

A duplicate upload keeps what its batch chose: the phone page's tags are *added* to the photo the
library already had, and its collections and favourite join the photo's pending metadata
(`photos.apply_upload_meta`, on every path an upload can take).

### 1.3 Categories and "recent"

A category (`tag_categories`: name, colour, position) groups tags **one level deep** — People,
Events and Themes to start with, renamable, deletable, and more can be added. A tag with none is
**Other**. Deleting a category keeps its tags: they become Other (`ON DELETE SET NULL`). The colour
lives on the category; a tag's own colour overrides it. The picker, the tag menu, the filter
chips and the Tags page group by category.

`tags.last_used_at` is touched whenever a tag gets attached to something; the picker and the tag
menu offer the **recent** ones first (`GET /tags?sort=recent`) — what you tagged the previous photo
with is what you want on this one. `sort=usage` (the default) and `sort=name` exist too.

There is **no "Places" category**, on purpose: a place is photo *metadata* the offline geocoder
fills from the GPS position, so the Tags page has a read-only **Places** tab instead
(`GET /places`, `services/places.py`): country → region → place, with photo and artwork counts per
level (an artwork made of photos from two cities counts once for their country), and the number
of photos without a position. A row opens the artworks filtered by that place
(`/artworks?place=…`, the `place` clause, "contains"). No nested tags either: a category is the one
level of grouping.

### 1.4 Later: keywords already in the files

Not built. Lightroom, digiKam, darktable and Apple exports write keywords into the file (XMP
`dc:subject` / `lr:hierarchicalSubject`, IPTC Keywords); phones rarely do. When it is built:
read them through libvips' metadata blobs as **untrusted input** (bounded length and count, no
entity expansion), put them in an "Imported" category — mapping a hierarchical `People|Alice` onto
category + tag — and keep it **idempotent**: receiving the same photo again must not duplicate or
resurrect a tag the user deleted on purpose.

Every mutation re-indexes the entities that carried the tag: a tag name is searchable text (§4).

## 2. Collections

`collections` is a tree (`parent_id`) with two kinds.

**Manual** — artworks added by hand, in `collection_items`, ordered by a REAL `position`.
Reordering writes one row (midpoint between neighbours) and renumbers the list only when the
doubles run out of room (`MIN_GAP = 1e-9`). Sibling collections are ordered the same way, which is
what makes a drag-and-drop move a single write.

**Smart** — a stored filter AST. It has no items of its own: `GET /artworks?collection_id=…`
compiles the filter instead of joining `collection_items`, so a smart collection updates live and
can never go stale. It holds no sub-collections either, and nothing about it is editable by hand —
no manual order, no *Add artworks*, no removal. The page says so rather than just withholding the
controls.

**One scoping path for both kinds.** `_in_collections` unions manual membership with the filters of
the smart collections among the ids, and the listing, the filter AST's `collection` clause and
`nested_count` all go through it. Looking only at `collection_items` made a smart *sub*-collection
contribute nothing to include-nested — its artworks are matches, not rows.

**Smart membership is derived**, so it is reported apart from the editable kind: an artwork carries
`collection_ids` (manual, add/remove) and `smart_collection_ids` (matched by a filter, read-only).
An artwork leaves a smart collection by ceasing to match it, never by being removed from it.

A collection's **parent is a field, not a gesture**: the create/edit dialog offers a parent picker
(`Top level` first, the collection's own subtree excluded), and the tree has a drop zone under it
that re-parents to the top level. Nesting must never be the only direction available.

Rules the server enforces:

- **cycles**: moving a collection inside its own subtree is 422 `collection_cycle` (the subtree
  comes from a recursive CTE, `subtree_ids`);
- **depth**: at most 8 levels, subtree included (`collection_too_deep`);
- **self-reference**: a smart collection's filter may not name itself, nor a smart collection whose
  own filter names it back (`filter_cycle`);
- **deletion is not a trash operation**: the collection and its subtree go, the artworks stay.

`include_nested` is answered by the same CTE, for both counts and listings. `nested_count` counts
**distinct** artworks — one filed in two sub-collections of a parent is one artwork, not two — and
resolves each smart descendant's filter once, reusing the result across the subtrees that contain it.

`position` only orders one collection's own items, so **manual order and include-nested are
exclusive**: the join that gives an artwork its position exists only in the collection it was
added to, and spanning a subtree would silently drop everything living in a child. The server
refuses the combination (422 `manual_sort_nested`) instead, and the collection page's sort picker
drops *Manual order* from its options while include-nested is on, so the fallback is visible.

Filing artworks works from either end: drag cards onto a row in the tree or the sidebar, use
*Add to collection* (`c`) from a grid or from the viewer, or open a collection and press
*Add artworks* to pick from the whole library.

## 3. The filter AST

`domain/filters.py` (pure) validates; `services/library.py` compiles. A node is a **group**
(`and` / `or` / `not`) or a **clause** (`field`, `op`, `value`).

| Field | Operators | Reaches |
|---|---|---|
| `tag` | `has_any` `has_all` `none` | `artwork_tags` **or** the `photo_tags` of a live photo it uses (§1.1) |
| `favorite`, `is_incomplete` | `eq` | the artwork column |
| `status` | `eq` `in` | idem |
| `worst_tier` | `in` | idem |
| `photo_count` | `eq` `gte` `lte` | idem |
| `title` | `contains` | idem |
| `created_at`, `updated_at` | `between` `before` `after` | idem |
| `collection` | `in` `not_in` (+ `include_nested`) | `collection_items`, or a smart collection's own filter |
| `taken_at` | `between` `before` `after` | **a photo the artwork uses** (EXISTS over `artwork_photos`) |
| `place` | `contains` | idem |
| `text` | `match` | the FTS index (§4) |

Bounds: 64 clauses, 4 levels, 200 values per clause. An empty group matches everything.

`taken_at` and `place` are the only clauses that leave the `artworks` table: an artwork is "from
Kyoto" when one of its photos is, which is the reading a user expects and the only one a
multi-photo artwork can support.

Dates are `YYYY-MM-DD` (or a full ISO stamp) turned into aware UTC bounds; `between` takes the end
day whole (`23:59:59.999999`).

Two entry points: `GET /artworks` for the flat cases (status, favourite, collection, `q`, sort) and
`POST /artworks/query` for an AST — a filter is too big and too nested for a query string.
`POST /filters/validate` answers "is this valid, and how many artworks does it match", which is
what the smart-collection editor shows while you type.

## 4. Search

The FTS5 table `search_index` (created by migration 0001) holds one row per entity:

- **artwork** — its title, its tags' names (its own and its photos', §1.1), and the file names and
  places of the photos it uses;
- **photo** — file name, place, camera, lens, tags;
- **collection** — name and description.

Writers keep it in sync inside the same transaction as the change (`services/search.py`), so the
index never outlives what it describes. It is nonetheless **disposable**: `reindex_all` rebuilds it
from the columns, and the app does that at startup when the table is empty — or when the marker
row says it was written under older rules than `search.INDEX_VERSION` (2: tag inheritance).

User text becomes a prefix query (`"kyo"*`), tokens only — everything FTS5 would read as an
operator is dropped. Photo search keeps a `LIKE` arm beside it so a fragment inside a word
(`IMG_1200`) still finds a file.

## 5. Trash

`photos.deleted_at` / `artworks.deleted_at` plus a shared `trash_batch_id`: **what is deleted
together is restored together**.

Deleting photos an artwork uses is a decision, so the API splits it in two:

1. `POST /trash/preview` lists the affected artworks (how many of their slots use the photos, and
   how many photos they hold in total);
2. `POST /trash/photos` takes a **cascade**:
   - `trash_artworks` — they go to the trash in the same batch;
   - `empty_slots` — they stay: the photo leaves their slots, which become placeholders
     (`quality_lock = free`, crop = the slot's rect), the artwork goes back to `draft`, and a
     `pre_trash` snapshot makes it undoable. The document goes back through `artworks.validated`,
     so a composition re-solves exactly as it would for a new artwork with a missing photo.

**Purge** is what frees disk (`trash.purge`): rows past `trash_retention_days` (30) are deleted for
good with their originals, thumbnails, proxies, palettes and render caches. It runs daily
(`JobQueue.schedule_every`, coalesced) and on demand — `all: true` empties the trash now.

Restoring puts a photo back and re-indexes it; nothing else about it changed (its import date, its
tags, its artworks are untouched), which is the same promise as receiving a photo again
(`docs/data-model.md`, *Photo copies*).

**Acting, then Undo.** The trash is reversible, so moving something there never asks first: it
happens, and a toast offers **Undo**, which restores exactly the batch that gesture created
(`features/trash/useTrashWithUndo.ts`). That covers `Delete` and the buttons on every grid and in
the viewer. The one question left is the cascade above, and only when an artwork actually uses
the photos: `useDeletePhotos` asks for the preview first and skips the dialog when nothing is
affected. The dialog opens on *Move to trash*, so **Enter** or **`Delete` again** confirms it.
After an `empty_slots` cascade no Undo is offered — restoring the photo would not refill the slots
(each artwork's `pre_trash` snapshot does) — and the toast says so.

## 6. The inbox and "ready"

The inbox is a **to-do list**: photos waiting for a *finished* artwork.

- A photo arrives in it (`inbox_state = inbox`), and comes back to it whenever it is received
  again (invariant 1, `receive_again`).
- Creating an artwork **does not** take its photos out: a draft is work in progress, and an
  abandoned draft must not make a photo vanish from the list. While a photo has drafts, its inbox
  tile shows a **Draft** badge that opens the (oldest) draft instead of inviting a second artwork
  (`PhotoOut.draft_artwork_ids`).
- **Marking an artwork ready** (`mark_ready` — `POST /artworks/{id}/validate` and `PATCH status:
  ready` both go through it) moves its photos from `inbox` to `processed`. That is the only
  automatic way out, and it is **one-way**: going back to draft, trashing the artwork or restoring
  it never puts a photo back. A `dismissed` photo stays dismissed.
- By hand: **Dismiss** (`d`) keeps the photo in the library but off the list; **Delete** trashes
  it (with Undo); **Back to inbox** (Photos page, selection or drawer — `POST /inbox/restore`)
  puts any photo back.

So **Ready** means *done*: the artwork was checked (complete, valid) and its photos left the
inbox. Nothing else gates on it (the TV and exports take drafts too). Libraries from before this
rule were not changed retroactively: photos already `processed` stay so, drafts included.

## 7. UI

| Place | What |
|---|---|
| Sidebar | the collection tree under the library links; a row opens *that* collection (`/collections?id=…`), and dropping artworks on one files them |
| Artworks / Favorites | the filter bar (chips), search, sort, multi-select, *Add to collection*, the tag menu (`t`), *Move to trash* (with Undo); `/artworks?place=…` / `?tag=<id>` open it with that chip |
| Collections page | tree with drag-and-drop (re-parent, reorder, drop-to-top-level), a parent picker in the dialog, sort picker, include-nested toggle (only where there *are* children), manual ordering by dragging a card, *Add artworks* |
| Artwork viewer | two rows — what it is and what you can do to it, then where it is filed: manual collections as plain badges, smart ones in accent with a sparkle (read-only), its own tags (editable in place — *Done* or `Esc` closes the editor, and moving to another artwork does too) and its photos' tags, dashed |
| Tags page | grouped by category: rename / recolour / delete a category, add one; per tag rename, own colour, category, merge, delete, counts (the artwork count links to the filtered grid); select tags to move them to a category; *Delete N unused tags*; a **Places** tab |
| Trash page | both lists, restore by item or by batch, purge expired, empty |
| Photos page | a tag filter (every tag, grouped) next to the search box; the tag menu (`t`); *Back to inbox*; `Delete` trashes with Undo, or opens the cascade dialog when artworks use the photos |
| Inbox | Draft badges; *Dismiss* (`d`) and *Delete* (`Delete`) kept apart; the tag menu (`t`) |
| Upload tray | *Tag these N photos…* for the batch that just landed, duplicates included |
| Editor | `f` toggles the artwork's favourite |
| Phone (`/m/browse`) | read-only: artworks, favourites, collections, full render on tap |

Favourites are an **artwork** property (the phone's upload screen sets it as pending metadata,
applied when the artwork is created). Photos have no heart of their own.

### Shortcuts

One hook (`useArtworkGridCommands`) gives every grid of artworks the same keyboard, so Artworks,
Favorites and a collection's page cannot drift: `c` add to collection · `t` tag · `f` favourite the
selection · `e` edit · `Delete` trash (Undo in the toast) · `/` search · `Ctrl/Cmd+A` select all ·
`Esc` clear. A collection adds
`Backspace` — taking an artwork *out of a collection* is a far gentler act than trashing it and
deserves its own key.
Navigation chords live in the shell: `g a` artworks, `g c` collections, `g f` favorites, `g p`
photos, `g i` inbox, `g t` tags, `g d` devices, `g s` settings.

A bare letter and a chord starting with the same letter are two bindings in two `tinykeys`
instances, and each matches on its own: `g c` used to navigate **and** open the add-to-collection
menu. `app/commands.ts` keeps one capture-phase listener that remembers whether the previous key
started a chord, and single-key bindings stand down for the keystroke after one.

Reordering a card inserts it **before** the drop target when dragging backwards and **after** it
when dragging forwards. "Always before" made a forward drag ask for the place the card already
had, so dragging right did nothing.

## 8. What is deliberately not here

- No per-collection cover picker in the UI yet (`cover_artwork_id` exists and the API accepts it).
- A `<select>` left transparent gets a native popup Chrome paints from the control's own colours —
  light popup, near-white options, readable only under the hover highlight. `styles.css` gives
  `select`/`option` an element-level colour and background so the fallback can never happen; any
  utility class on a specific select still wins.
- No tag colours beyond six presets: a tag list is not a palette editor. A colour is a dot beside
  the name, never the text's colour, so a pale one stays readable in both themes (invariant 16).
- No nested tags and no "Places" category (§1.3); no keyword import yet (§1.4).
- Photo-side smart collections: collections hold artworks (`docs/data-model.md` §5.1).
