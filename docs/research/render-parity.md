# S3 — Preview/render parity (deferred to the start of Phase 4)

S3 compares Konva (browser) and pyvips (server) for shadows, textures and captions. It needs the renderer
(Phase 4) and a canvas prototype, so it is executed as the **first task of Phase 4**, before the editor work of
Phase 5 depends on its conclusions. The mapping formulas to verify are in `docs/rendering-spec.md` §8.2.
