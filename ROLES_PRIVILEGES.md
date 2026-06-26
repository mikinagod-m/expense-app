# Roles & privileges

Who can do what in the expense app is stored in the database — **not** in Azure AD (yet).

## Roles

| Role | How it is assigned | What it allows |
|------|-------------------|----------------|
| **Claimant** | Everyone | Submit and edit own claims |
| **Manager** | Has one or more direct reports (`manager_id` on users) | Approve/reject team claims |
| **Finance** | `is_finance` checkbox | Process claims, exports, periods, reconciliation |
| **Admin** | `is_admin` checkbox | Manage users & roles at `/admin/users` |

Finance users also see manager navigation (they can approve any claim).

## Entitlements

| Flag | Effect |
|------|--------|
| `can_claim_cash` | User sees open **cash** periods and can start cash claims |
| `has_credit_card` | User sees open **card** periods and can start card claims |

## Admin UI

**Finance → sidebar → Users & roles** (admin only)

- Add users before first Azure login (name + email)
- Set manager, finance, admin, card, and cash flags
- Changes are audit-logged (`user.create`, `user.update`)

## Azure AD relationship

When `DEV_LOGIN=0`, Microsoft login only creates/updates **name, email, and Azure OID**.

Privileges must still be assigned here (or via future group-mapping in P3-04).

## Pilot defaults

Seed user **Morgan Hale** is finance + admin. Direct reports **Jordan Blake** and **Riley Stone** have card access.

Existing databases get `is_admin` added on startup; current finance users are promoted to admin automatically.
