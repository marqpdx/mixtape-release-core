# Mixtape Groups — Types, Decorators, Containment, and Roles (Updated Overview)

This document reflects refinements from the **Business Design Team**. It preserves our agreed-upon four-type group structure and decorator system but clarifies relationships between **roles**, **decorators**, and **permissions**, as well as adding formal catalog and profile models.

---

## 1) Core Group Types (Unchanged)

We retain four concrete types under one base `Group` model:

* **Persona** — a personal container (often 1:1 with `User`), can contain **Circles**.
* **Circle** — atomic team; cannot contain groups.
* **Community** — larger collective; can contain **Circles**.
* **Coalition** — federation; can contain any type.

> Containment rules remain enforced by the `GroupContainment` model (Persona→Circle only, Circle→none, Community→Circle, Coalition→any).

---

## 2) Single Membership Record per User per Group

Instead of multiple membership rows (e.g., one for founder, one for admin), each person has **one membership record** per group with a **roles list** and attached decorators.

**Example:**

```python
Jane creates a band → roles=['founder', 'admin']
Jane steps down as admin → roles=['founder', 'member']
```

**Benefits:**

* Single source of truth for relationship state
* Simplified queries and lifecycle updates
* All membership decorators attach to one record

---

## 3) Founder as Membership Decorator (Not a Role)

Roles remain only **admin**, **steward**, and **member**.
**Founder** becomes a **membership decorator** (`isGroupFounder`), not a separate role.

* Grants no special permissions
* Permanent badge/identity marker
* Displayed visually in UI (flair, badges)

This keeps roles minimal and flexible while enabling richer identity expression.

---

## 4) Decorator System — Parallel Group ↔ Membership Structure

Both **groups** and **memberships** follow the same naming and categorization logic.

### Group Decorators

* **Identity (`isA__*`)** — what the group *is*
  *Examples:* `isA__Band`, `isA__ReadingCircle`
* **Capability (`can__*`)** — what it *can do*
  *Examples:* `can__HostEvents`, `can__HaveThreadworks`
* **Policy (`policy__*`)** — how it *behaves*
  *Examples:* `policy__InviteOnly`, `policy__PrivateByDefault`

### Membership Decorators

* **Identity (`isGroup__*`)** — what the member *is*
  *Examples:* `isGroupArchivist`, `isGroupFounder`
* **Permission (`can__*`)** — what they *can do*
  *Examples:* `can__CreateEvents`, `can__ModeratePosts`
* **Policy (`policy__*`)** — what rules apply to them
  *Examples:* `policy__CanSeePrivatePosts`

> Consistent structure = intuitive mental model and simplified logic.

---

## 5) Decorator Profiles (Group & Membership)

### Group Profiles

Bundles of decorators applied to a `Group` at creation (e.g., Band, PTA, Study Circle).

**Example: Band Profile**

* `isA__Band`, `can__HostEvents`, `can__HaveThreadworks`, `policy__InviteOnly`

### Membership Profiles

Bundles for member decorators + permissions.

**Example: Archivist Profile**

* Identity: `isGroupArchivist`
* Permissions: `can__EditPosts`, `can__ModerateComments`, `can__ManageThreadworks`
* Requires: Steward role minimum

**Example: Event Coordinator Profile**

* Identity: `isGroupEventCoordinator`
* Permissions: `can__CreateEvents`, `can__ManageRSVPs`, `can__SendEventNotifications`
* Requires: Member role

**Purpose:** Apply complex decorator sets in one action.
Allows delegated permissioning without adding roles.

---

## 6) Permission Resolution Model

Permissions are resolved in layers:

1. **Admin always wins** — all permissions.
2. **Base role permissions** — Stewards inherit limited admin powers.
3. **Decorator-granted permissions** — additive from decorators or profiles.

**Example:**

```text
Alice = Member + can__CreateEvents → can create events only
Bob = Steward + can__EditPosts → can edit but not admin settings
```

**Outcome:**
Fine-grained delegation without role explosion.

---

## 7) Decorator Catalogs and Relationships

All decorators are defined in **catalog tables**, not hardcoded constants.

### Models

* **GroupDecorator** — defines available group decorators
* **MembershipDecorator** — defines available membership decorators

Each catalog entry includes:

* Code, category, label, description
* Valid for (group types)
* `implies` (auto-adds other decorators)
* `conflicts_with` (exclusions)
* `requires_role` (min role requirement)

**Assignment Models:**

* `GroupHasDecorator` — attaches to a group
* `MembershipHasDecorator` — attaches to a membership

**Profile Models:**

* `GroupDecoratorProfile`
* `MembershipDecoratorProfile`

**Benefits:**

* No schema changes to add new decorators
* Seed from YAML/config
* Declarative enforcement of dependencies/conflicts

---

## 8) Key Confirmations (What Hasn't Changed)

✅ Four group types and containment model
✅ Three core roles: Admin, Steward, Member
✅ Decorator-based identity/capability architecture
✅ Centralized containment rules in data model
✅ Separation of structure (type) vs identity (decorators) vs permission (roles/decorators)
✅ Query efficiency and composable flexibility

---

## 9) Implementation & Business Benefits

* **Flexibility without schema churn** — decorators define new behavior
* **Simple core roles** — admin/steward/member remain universal
* **Composable power** — bundles and decorators enable rich specialization
* **Declarative permissioning** — clarity and auditability
* **Future-proofing** — add new categories or profiles with no migrations

---

## 10) Conceptual Examples (Retained)

### Band Circle

* Type: Circle
* Group decorators: `isA__Band`, `can__HostEvents`, `policy__InviteOnly`
* Creator: Jane (roles=['admin'], decorators=['isGroupFounder'])
* Member: Bob (roles=['member'], decorators=['isGroupEventCoordinator', 'can__CreateEvents'])

### Neighborhood Community

* Type: Community
* Group decorators: `isA__NeighborhoodAssociation`, `can__HostEvents`, `can__InviteByLink`
* Contains: Beautification Circle, Block Watch Circle
* Member: Alice (roles=['steward'], decorators=['isGroupTreasurer', 'can__ViewFinancials'])

### Coalition

* Type: Coalition
* Group decorators: `isA__RegionalCoalition`, `can__FederateContent`, `policy__ModeratedForums`
* Archivist: Carlos (roles=['steward'], decorators=['isGroupArchivist', 'can__EditPosts', 'can__ModerateComments'])

---

## 11) Open Questions

1. **Decorator Management UI:** Should group admins be able to define custom decorators or be limited to catalog entries?
2. **Permission Granularity:** How fine-grained should decorators get? (e.g., `can__EditOwnPosts` vs `can__EditAnyPost`)
3. **Profile Evolution:** Can profiles be updated version-wise, and should groups auto-receive updates?
4. **Audit Logging:** Should decorator grants/removals be logged (for moderation transparency)?
5. **Frontend UX:** How to visualize decorator-based permissions — badges, roles+decorators display, tooltips?
6. **Conflict Resolution:** How should mutually exclusive decorators be presented or resolved in UI?
7. **Role Enforcement:** When a decorator requires a minimum role, how should assignment fail or warn?

---

## 12) Light Next Steps

1. **Finalize catalog schema** — confirm fields for code, category, valid types, implies/conflicts.
2. **Implement decorator validation layer** — enforce requires/implies/conflicts logic.
3. **Add membership roles list** — array or JSONField to support multi-role lifecycle.
4. **Design UI prototypes** — decorator and profile assignment flows for Admins.
5. **Seed base catalog** — YAML fixtures for initial decorators and profiles.
6. **Write unit tests** — containment, decorator validation, and permission resolution.

---

*Updated October 2025 — incorporates Business Design Team refinements.*
