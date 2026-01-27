# Emblem Endpoints — Pre‑Test Checklist

> Purpose: quick sanity validation of emblem attach/reset endpoints and serializer shape.
> Scope: manual/API checks (no code changes).

---

## 1) Attach emblem to group

**Request**
- `POST /api/groups/{slug}/emblem/attach`
- Body: `{ "emblem_id": "<uuid>" }`
- Auth: group admin or steward

**Expectations**
- 200 OK
- Response includes `emblem` object with at least one URL field (`size_96_url` or `url`).
- Group model now references the emblem (subsequent GET returns same emblem).

---

## 2) Reset emblem

**Request**
- `POST /api/groups/{slug}/emblem/reset`
- Auth: group admin or steward

**Expectations**
- 200 OK
- Response includes `emblem: null` (or emblem omitted).
- Subsequent GET returns `emblem: null`.

---

## 3) Permissions

**Requests**
- Repeat attach/reset as:
  - member (non‑steward)
  - non‑member

**Expectations**
- 403 Forbidden

---

## 4) Serializer shape (detail)

**Request**
- `GET /api/groups/{slug}`

**Expectations**
- `emblem` present when set
- `emblem` null when not set
- `emblem` includes URL fields (`size_96_url` or `url`)

---

## 5) Serializer shape (list)

**Request**
- `GET /api/groups` (or `/api/groups/my`)

**Expectations**
- `emblem` present per group and matches detail endpoint

---

## Notes

- Use any existing EmblemAvatar from the identity library.
- If uploads are needed, use `POST /api/identity/emblem-image` then `POST /api/identity/emblem-avatars` to create an emblem.
