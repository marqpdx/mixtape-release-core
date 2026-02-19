# Dispatch Outline v1 Backend Test Plan

Scope: Validate persistent outline nodes for Dispatch (WritingPiece-native).

Endpoints under test:
- `GET /api/dispatch/outline/{piece_id}`
- `POST /api/dispatch/outline`
- `PATCH /api/dispatch/outline/node/{node_id}`
- `DELETE /api/dispatch/outline/node/{node_id}`

Assumptions:
- Auth user can create and edit their own WritingPiece.
- Collaborators are defined via `WorkingDocument.dispatch_content` and `DispatchContent.collaborators`.

---

## Preconditions (setup)
- Create user `u1` and `u2`.
- Create a `WritingPiece` owned by `u1`, `writing_kind = dispatch`.
- Ensure `WritingPiece.enable_outline = false` initially.
- Create a `WorkingDocument` for the piece.
- (For collaborator tests) attach a `DispatchContent` to the WorkingDocument and add `u2` as collaborator.

---

## A) Opt-in gate

### A1. Outline disabled returns empty
Steps:
1) `GET /api/dispatch/outline/{piece_id}` as `u1`.
Expected:
- `200` with `[]`.

### A2. Create blocked when disabled
Steps:
1) `POST /api/dispatch/outline` with `{ writing_piece, title }` as `u1`.
Expected:
- `400` with message “Outline is not enabled for this piece.”

---

## B) Enable outline

### B1. Enable and create root node
Steps:
1) PATCH the WritingPiece to set `enable_outline = true`.
2) `POST /api/dispatch/outline` with `{ writing_piece, title: "Intro", anchor_target: <uuid> }`.
Expected:
- `201` with node fields.
- `order_index` defaulted to 0 if omitted.

### B2. Get outline returns tree
Steps:
1) `GET /api/dispatch/outline/{piece_id}`.
Expected:
- `200` with array of nodes, root(s) at top.

---

## C) Parent/child rules

### C1. Create child node
Steps:
1) Create child with `parent = root_id`.
Expected:
- `201`, child nested under `children` when fetched.

### C2. Parent must belong to same piece
Steps:
1) Create another WritingPiece (piece B).
2) Try to create node for piece A using parent from piece B.
Expected:
- `400` validation error on `parent`.

### C3. Prevent self-parent
Steps:
1) PATCH node with `parent = self_id`.
Expected:
- `400` validation error.

---

## D) Reordering

### D1. Update order_index
Steps:
1) Create two sibling nodes.
2) PATCH one to `order_index = 0`, the other to `order_index = 1`.
Expected:
- `GET` returns siblings ordered by `order_index`, then created_at.

---

## E) Anchor handling

### E1. Allow null anchor
Steps:
1) Create node with `anchor_target = null`.
Expected:
- `201` with `anchor_target: null`.

### E2. Update anchor target
Steps:
1) PATCH node with new `anchor_target`.
Expected:
- `200` with updated value.

---

## F) Permissions

### F1. Author can read/write
Steps:
1) As `u1`, list, create, patch, delete.
Expected:
- All succeed.

### F2. Collaborator can read/write
Steps:
1) As `u2` (collaborator), list, create, patch, delete.
Expected:
- All succeed.

### F3. Non-collaborator denied
Steps:
1) As `u3` (no access), attempt list/create/patch/delete.
Expected:
- `403`.

---

## G) Delete

### G1. Delete node
Steps:
1) `DELETE /api/dispatch/outline/node/{node_id}`.
Expected:
- `204`; node no longer appears in tree.

---

## H) Regression checks

### H1. WritingPiece list/detail includes enable_outline
Steps:
1) Fetch WritingPiece list and detail endpoints.
Expected:
- `enable_outline` present and correct.

---

## Deliverables to capture
- Example JSON tree from `GET /api/dispatch/outline/{piece_id}`.
- Screenshot or response snippets for permission denials (`403`) and validation (`400`).
