# Mixtape Release Backend - Local Setup

## Directory Structure

```
mixtape-release-core/
├── app/                      # Django application code
│   ├── manage.py            # Django management script
│   ├── accounts/            # Authentication app
│   ├── users/               # CustomUser, Role models
│   ├── profiles/            # UserProfile, Member API
│   ├── fundamentals/        # BaseModel
│   └── mixtape/             # Project settings
│       ├── settings/
│       │   ├── base.py
│       │   ├── dev.py
│       │   └── prod.py
│       ├── urls.py
│       └── wsgi.py
├── env/                     # Virtual environment (gitignored)
├── requirements.txt         # Python dependencies
└── .env                     # Environment variables (create this)
```

---

## 1. Setup Virtual Environment

```bash
cd mixtape-release-core

# Activate the virtual environment
source env/bin/activate  # On macOS/Linux
# OR
env\Scripts\activate     # On Windows

# Install dependencies
pip install -r requirements.txt
```

---

## 2. Create `.env` File

Create a `.env` file in the `mixtape-release-core/` directory:

```bash
# mixtape-release-core/.env

# Django Settings
DJANGO_ENV=dev
DJANGO_SECRET_KEY=your-secret-key-here-change-in-production
DEBUG=True

# Database (SQLite for local dev)
# Leave empty to use default SQLite
# DATABASE_URL=postgresql://user:password@localhost:5432/mixtape_release

# JWT Settings
ACCESS_TOKEN_SIGNING_KEY=your-jwt-signing-key-here

# CORS is already configured in base.py for localhost:3010

# Optional: Email settings (for later)
# EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

**Generate secret keys**:
```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

---

## 3. Run Migrations

```bash
cd app  # Important: navigate into app/ directory

# Create migrations
python manage.py makemigrations

# Apply migrations
python manage.py migrate
```

**Expected output**: Creates database tables for users, profiles, fundamentals, accounts

---

## 4. Create Superuser

```bash
python manage.py createsuperuser

# Follow prompts:
# Username: admin
# Email: admin@example.com
# Password: (your choice)
```

---

## 5. Create Profile for Superuser

The User model exists, but we need to create a Profile manually:

```bash
python manage.py shell
```

In the shell:
```python
from users.models import CustomUser
from profiles.models import UserProfile

# Get the superuser
user = CustomUser.objects.get(username='admin')

# Create profile
profile = UserProfile.objects.create(
    user=user,
    display_name='Admin User',
    quick_intro='System administrator'
)

print(f"✅ Profile created with slug: {profile.slug}")
exit()
```

---

## 6. Start Development Server

### Option 1: Using the dev script (easiest)

```bash
# From mixtape-release-core/ directory
./dev.sh
```

### Option 2: Manual command

```bash
# Make sure you're in the app/ directory
cd app

# Start server on port 8010
python manage.py runserver 8010
```

**Expected output**:
```
Starting development server at http://127.0.0.1:8010/
```

---

## 7. Test the API

### Test Authentication

```bash
# Login
curl -X POST http://localhost:8010/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{"identifier": "admin", "password": "YOUR_PASSWORD"}'

# Expected response:
# {
#   "success": true,
#   "access": "eyJ...",
#   "access_expires": 1234567890,
#   "refresh": "eyJ...",
#   "refresh_expires": 1234567890,
#   "user": {
#     "id": "...",
#     "username": "admin",
#     "email": "admin@example.com"
#   }
# }
```

### Test /auth/me

Copy the `access` token from the login response:

```bash
curl http://localhost:8010/api/auth/me \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"

# Expected response:
# {
#   "id": "...",
#   "username": "admin",
#   "email": "admin@example.com",
#   "is_superuser": true,
#   "is_staff": true,
#   "roles": ["member"],
#   "profile": {
#     "id": "...",
#     "bio": ""
#   },
#   "groups": []
# }
```

### Test Member Endpoints

```bash
# List all members
curl http://localhost:8010/api/members/

# Get member by slug
curl http://localhost:8010/api/members/admin-user

# Expected response:
# {
#   "id": "...",
#   "username": "admin",
#   "email": "admin@example.com",
#   "first_name": "",
#   "last_name": "",
#   "is_active": true,
#   "date_joined": "...",
#   "roles": ["member"],
#   "slug": "admin-user",
#   "display_name": "Admin User",
#   "quick_intro": "System administrator",
#   "avatar_url": "",
#   "created_at": "...",
#   "updated_at": "..."
# }
```

---

## 8. Django Admin

Access the admin at: http://localhost:8010/admin/

Login with your superuser credentials.

You can:
- View/edit users
- View/edit profiles
- Manage roles

---

## Common Issues & Solutions

### Issue: `ModuleNotFoundError: No module named 'django'`
**Solution**: Make sure virtual environment is activated:
```bash
source env/bin/activate
pip install -r requirements.txt
```

### Issue: `django.core.exceptions.ImproperlyConfigured: No SECRET_KEY`
**Solution**: Create `.env` file with `DJANGO_SECRET_KEY`

### Issue: `ImportError: cannot import name 'X' from 'Y'`
**Solution**: One of the removed apps is being imported. Comment out the import in settings or the referencing file.

### Issue: Migrations fail with dependency errors
**Solution**: May need to fake migrations for removed apps:
```bash
python manage.py migrate <app_name> --fake
```

### Issue: Profile not created automatically on signup
**Solution**: For Phase 1, profiles are created manually. In Phase 2, we'll add a signal to auto-create profiles.

### Issue: `ImproperlyConfigured` / bad-value errors for a setting that's clearly in `.env` (production servers)
**Cause**: `load_dotenv()` in `base.py`/`prod.py` loads `.env` from `BASE_DIR`, which resolves to the
Django project directory (same level as `manage.py` — locally, `mixtape-release-core/app/.env`). On the
`crossroads` production server, the repo is checked out one level up from where you'd expect
(`/var/www/crossroads/app/` is the repo root), so the canonical `.env` lives at
`/var/www/crossroads/app/app/.env` to match — **not** `/var/www/crossroads/.env`.

If `.env` was placed at the repo root instead, `load_dotenv()` silently finds nothing (no error) and
falls through to whatever's already in the process's environment. The live site itself is unaffected —
gunicorn's systemd unit sets env vars directly via `EnvironmentFile=`, independent of `load_dotenv()` —
but any `manage.py` command run manually from an SSH shell will only see vars that happen to already be
exported in that shell session, which can mask this for a long time until a genuinely new var is needed.

**Solution**: keep a symlink from the repo-root `.env` into the Django project dir so both the systemd
service and manual `manage.py` invocations resolve to the same file:
```bash
ln -s /var/www/crossroads/.env /var/www/crossroads/app/app/.env
```
Verify with `python -c "import os; print(repr(os.environ.get('YOUR_VAR')))"` run from a plain shell
(not just via a running service) after any new env var is added.

---

## Development Workflow

### Daily Start

**Quick start** (from mixtape-release-core/ directory):
```bash
./dev.sh
```

**Manual start**:
```bash
cd mixtape-release-core
source env/bin/activate
cd app
python manage.py runserver 8010
```

### Making Model Changes
```bash
# 1. Edit models.py
# 2. Create migration
python manage.py makemigrations

# 3. Apply migration
python manage.py migrate
```

### Creating New Users (for testing)
```bash
python manage.py shell
```
```python
from users.models import CustomUser, Role
from profiles.models import UserProfile

# Create user
user = CustomUser.objects.create_user(
    username='testuser',
    email='test@example.com',
    password='testpass123',
    first_name='Test',
    last_name='User'
)

# Add member role
member_role, _ = Role.objects.get_or_create(name='member')
user.roles.add(member_role)

# Create profile
profile = UserProfile.objects.create(
    user=user,
    display_name='Test User',
    quick_intro='Just testing'
)

print(f"Created user: {user.username} with profile: {profile.slug}")
```

---

## Next Steps

Once backend is working:
1. ✅ Test all auth endpoints
2. ✅ Test member endpoints
3. → Wire up frontend (axios + TanStack Query)
4. → Create login page
5. → Test full authentication flow

---

*Last updated: 2025-11-10*
