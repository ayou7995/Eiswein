# Schwab Developer Portal — User Guide Reference

**Source**: Schwab Developer Portal → User Guides
**Captured**: 2026-04-21 (transcribed from portal screenshots)
**Scope**: Portal usage only — how to register, create Apps, manage callbacks, promote to production. The OAuth *wire protocol* details (authorize URL, scopes, token request shape, PKCE) are in `oauth.md` (still partially blocked on the Trader API product docs).

---

## 1. Registration & Account Setup

### User Registration

- Register via the top-right **Register** button.
- Complete registration form (First/Last Name, Email+Verify, Country Code, Phone Number, accept T&Cs).
- Email is the **username**.
- Phone number is required for **two-factor authentication**.
- After submit, receive a validation email with a time-sensitive link.
- Internal Schwab employees skip registration and use **"Use your Schwab Credentials"** at login.

**Notes**:
- If joining an existing Company, the Company Admin must invite you.
- If your Company doesn't exist in the Dev Portal, you need to create a Company Profile to request API access.

### Profile Types

After first login, choose a profile on the Welcome page:

| Profile | When to use | Notes |
|---|---|---|
| **Individual Developer** | Personal-use app against your own Schwab brokerage account. | **This is Eiswein's profile.** Limited to **1 App**. Requires a Schwab brokerage account for Trader APIs. |
| **Join an Existing Company** | Joining an organization already on the portal. | Need an invite from the Company Admin. |
| **New Company** | Registering as a business/legal entity. | You become Company Admin of a new profile. |

### Individual Developer Role — Management

**To add the role**:
- Welcome Page: Locate "Individual Developer" card → click **CONTINUE**
- User Profile: Profile link → "Individual Developer" section → click **Add Individual Developer Role**

**To remove the role**:
- Profile → Roles table → Actions column → **Remove**

**Warning on removal**:
- All LOB subscriptions tied to the Individual Developer role are removed.
- **All Apps created under that role are deleted. Irreversible.** Don't click Remove on a live Eiswein app.

---

## 2. API Products & Line of Business (LOB)

### How They're Organized

- API Products are grouped by Schwab internal **Line of Business (LOB)**.
- Each LOB owns its own access-request form, approval workflow, and agreement.
- Documentation and access are provided **per LOB**.

### Available LOBs (from API Products page)

| LOB | Description | Eiswein relevance |
|---|---|---|
| **Account and Client Data** | Balances, Positions, Transaction History, ACH, Profile, Statements via FDX 3.0/4.6 + OAuth 2.0 | Not primary — Trader API covers this for personal use |
| **Advisor Services** | Custodial data + transactional services for Advisor platforms / RIAs | Skip — not applicable |
| **Data Aggregation Services** | Account Aggregation for clients using Schwab credentials | Skip |
| **Tax Data** | Tax Preparation Software providers | Skip |
| **Trader API - Commercial** | Distribution to other self-directed Schwab accounts | Skip |
| **Trader API - Individual** | Your own personal-use app for your own Schwab account — **account info, market data, trades** | **✅ This is Eiswein's LOB** |

### Requesting Product Access

1. Select **API Products** from top nav.
2. Click **Learn More** on the LOB card (e.g., "Trader API - Individual").
3. On the LOB page, click **Request Access** (green button).
4. Access requests reviewed within ~2 business days.

**Important**:
- **Company Admin** is the one who requests access on behalf of a Company. Company Developers contact their Admin.
- **Individual Developer** role is required for certain LOBs (including Trader API - Individual).
- If there's no "Request Access" button, that LOB isn't available to your Role.
- Access agreements bind **all members** of the Company once the Admin accepts.

---

## 3. Company Management (Skip for Eiswein)

Eiswein uses the **Individual Developer** path, so Company features don't apply. Captured here for completeness.

### Company Roles

| Role | Permissions |
|---|---|
| **Company Admin** | Request LOB access, accept agreements, modify profile, invite/remove/promote developers, promote apps to prod, periodic User access attestation |
| **Company Developer** | Create/manage Company Apps, read documentation, Try Now, request Support |

- Creator of a Company Profile auto-becomes Company Admin.
- Admins **cannot self-remove** — must promote another member first.
- Removing a role deletes apps — irreversible.

### Create / Edit Company Profile

- Create from Welcome Page ("New Company" card → Create) or from the in-portal menu (**Create Company**).
- Required fields: Company Name, Business Address, Company Website, App Use Cases.
- Company Name is **locked after creation** — support ticket required to rename.
- Must have at least one approved API Product before inviting developers.

### Invite Developers

1. Dashboard → bottom-of-page **Invite User** field → enter email → **Invite**.
2. Invitee receives registration/invite email.
3. **Invitations expire in 7 days.** Resend from Members Table.

**Role Selector**: if a user has multiple company memberships, a top-nav dropdown appears to switch contexts.

---

## 4. App Lifecycle

### Create an App

**Prerequisites**: Either be a Company member OR an Individual Developer, **and** approved for the target API Product.

**Steps**:
1. Dashboard → Apps → **Create App**
2. Fill in:
   - **App Name** — user-facing name (shown to end users during OAuth consent)
   - **Callback URL** — where Schwab redirects after authorization (see §6)
3. Select the API Product to subscribe.
4. Submit.

**Eiswein's App values** (already created 2026-04-20):
- Name: **Eiswein**
- Callback URL: **`https://127.0.0.1:8182/api/v1/auth/schwab/callback`**
- API Product: Trader API - Individual

**App Status lifecycle**:

| Status | Meaning |
|---|---|
| **Pending** | Awaiting Admin review. |
| **Sandbox** | Sandbox access approved, ready for testing. |
| **Active (Approved)** | Production — live and usable. |
| **Rejected/Denied** | Not approved. Contact Support. |
| **Inactive (Revoked)** | Disabled, cannot be used until re-activated. |

**On approval**: App Key (Client ID) and Secret (Client Secret) are shown in App Details. Treat as highly confidential.

### Modify an App

- Dashboard → Apps → View Details on target App → **Modify**
- Can change: **App Name**, **Callback URL**
- Cannot change: API Product subscription, Client ID/Secret.

### Deactivate / Activate

- Deactivate: Apps → View Details → **Deactivate App** → confirm. Pauses the app (Client ID is rejected during OAuth).
- Activate: same flow with **Activate App** button.

### Sandbox Testing

- Sandbox environment available for most LOBs — simulated data, same OAuth 2.0 flow.
- RESTful API, Swagger/OpenAPI specs provided.
- Use for dev/test; real accounts and real data are NOT exposed.

### Promote to Production

1. Dashboard → Apps → View Details on Sandbox App → **Promote to Production**.
2. Confirmation modal opens with editable App Name, Description, Callback URL(s).
3. Click **Promote App**.
4. **May require manual LOB admin approval — can take several days.**
5. Sandbox App remains after promotion (both versions kept).

**Note**: For LOBs that skip Sandbox (like Trader API - Individual per our experience — we went straight to Ready-for-use), this step may not appear.

---

## 5. OAuth Restart vs. Refresh Token (important!)

Tells us when the **Refresh Token flow is enough** vs. when we need to restart the **whole OAuth dance** from step 3 in `oauth.md`.

### Use Refresh Token when:
- `access_token` has expired normally (`expires_in` elapsed)
- `access_token` was lost from memory but not compromised (e.g. app restart)
- Proactively mitigating a `401 Unauthorized` before it fires

**→ Eiswein's `_authorized_request()` uses this path 99% of the time.**

### Full OAuth Restart required when:
- `refresh_token` itself is compromised or malfunctioning
- A **new `scope` value** is needed that wasn't on the current `access_token`
- A **new account** needs to be authorized (user wants to add/change Schwab accounts)
- User **revokes token access manually**, changes credentials, or modifies TFA
- Schwab pushes security policy changes requiring re-consent
- Documented/unknown technical errors on the refresh endpoint itself

**→ Eiswein's UI handles this by showing "請重新連接 Schwab" and sending the user back through Settings → 連接 Schwab.**

### Key facts confirmed from this doc:
- Token response JSON includes an **`expires_in`** field (seconds) — use this, don't assume 30 min.
- Grant type is `authorization_code` (confirmed).
- "Authorize an App" is the step name Schwab uses for what RFC 6749 calls the authorization-code exchange.

---

## 6. Callback URL — Rules (Deeply Relevant)

### Requirements

1. **URL Scheme**: Some LOBs require **HTTPS** (Trader API - Individual likely does — our URL is `https://...`).
2. Callback URLs are validated for basic URL structure.
3. Callback URLs are validated for "no special or unsupported characters".
4. If the OAuth flow **doesn't include `redirect_uri`** in the request, Schwab defaults to the one registered with the App.
   - But if **multiple** callback URLs are registered and request omits `redirect_uri`, Schwab returns an error (ambiguity).
   - **→ Eiswein should always explicitly include `redirect_uri` on `/oauth/authorize`** to avoid this ambiguity.
5. The Callback URL sent during OAuth **MUST be character-for-character identical** to one of the registered URLs. `//authorize` endpoint enforces this strictly.

### Multiple Callback URLs

- Supported on a single app.
- Comma-separated, **no space after the comma**: `https://a.example/cb,https://b.example/cb`
- Field limit: **255 characters** (per the official Schwab & API Security doc; the portal User Guides say 256 — we use the smaller value).
- Must be edited together (via Modify App or Promote-to-Production flow).

### Common errors (from Schwab's table)

| Registered | Sent in `/authorize` | Result |
|---|---|---|
| `https://host/path` | `https://host/path` | ✅ Successful |
| `https://host/path` | `myapp://blah/bam` | ❌ `invalid URI specified` (scheme mismatch) |
| `myapp://blah/bam` | `https://host/path` | ❌ scheme mismatch |
| `https://host/path` | `http://host/path` | ❌ scheme mismatch (https ≠ http) |
| `myapp://this/that` | `myapp://host/path` | ❌ `path sent does not match registered` |
| `myapp://this/that` | `myapp://this/that` | ✅ Successful |

**→ Eiswein's implementation invariant**: the `REDIRECT_URI` constant lives in `backend/app/config.py`, is used verbatim on both `/start` and `/callback`, and must be byte-equal to the value in the Schwab Dev Portal. Drift is the #1 cause of silent OAuth failures.

---

## 7. Sandbox — Not Used by Eiswein

The portal has a Sandbox environment with simulated data and Try-Now utilities. Our Trader API - Individual app went directly to "Ready for use" (production) — likely because Individual profile doesn't require Sandbox testing for personal-use apps. If we ever need Sandbox for development, we'd:
1. Create a separate Sandbox App (or use the Test in Sandbox flow on our existing app if available).
2. Test against sandbox OAuth URL (likely a separate host — TBD from Trader API product docs).
3. Promote to Production when ready.

For now: **we operate against production directly**.

---

## 8. What's Still Missing (for Phase S1 OAuth implementation)

These User Guides pages cover **portal usage** but NOT the wire protocol. To finish `oauth.md` we still need the **Trader API - Individual** API documentation pages:

- `GET /v1/oauth/authorize` — exact URL, required query params, valid `scope` values
- `POST /v1/oauth/token` — exact URL, request body shape (form vs JSON, Client Secret in body vs Basic Auth header), response JSON structure
- Explicit token lifetimes (access_token `expires_in`, refresh_token validity)
- PKCE requirement (`code_challenge` / `code_verifier` — RFC 7636)
- OAuth error response JSON envelope

These live under: **API Products → Trader API - Individual → (documentation section)**, not under the User Guides that were pasted here.
