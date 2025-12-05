# Manual Testing Guide - Image Upload/Commit/Rollback

## Quick Test with Django Shell

### Setup

```bash
# Start Django shell
DJANGO_SETTINGS_MODULE=mixtape.settings.dev python manage.py shell
```

### Test 1: Upload Image

```python
from django.test import Client
from django.contrib.auth import get_user_model
from groups.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image
import io

# Create test image
img = Image.new('RGB', (100, 100), color='red')
img_io = io.BytesIO()
img.save(img_io, format='PNG')
img_io.seek(0)

# Get existing user and group (or create them)
User = get_user_model()
user = User.objects.first()  # Use existing user
group = Group.objects.first()  # Use existing group

print(f"Testing with user: {user.email}")
print(f"Testing with group: {group.id}")

# Create authenticated client
client = Client()
client.force_login(user)

# Upload image
response = client.post(
    f'/api/assets/upload?sponsor_type=group&sponsor_id={group.id}&role=profile_image',
    {'file': SimpleUploadedFile('test.png', img_io.getvalue(), content_type='image/png')},
    format='multipart'
)

print(f"Upload status: {response.status_code}")
if response.status_code == 201:
    data = response.json()
    print(f"✓ Upload successful!")
    print(f"  Path: {data['path']}")
    print(f"  URL: {data['url']}")
    new_key = data['path']
else:
    print(f"✗ Upload failed: {response.json()}")
```

### Test 2: Commit Image

```python
# Get current image path (before commit)
group.refresh_from_db()
old_key = group.profile_image_path
print(f"Old key: {old_key}")

# Commit the new image
response = client.post(
    '/api/assets/commit',
    {
        'sponsor_type': 'group',
        'sponsor_id': str(group.id),
        'role': 'profile_image',
        'new_key': new_key,
        'old_key': old_key
    },
    content_type='application/json'
)

print(f"Commit status: {response.status_code}")
if response.status_code == 200:
    print(f"✓ Commit successful!")
    print(f"  {response.json()}")

    # Verify DB updated
    group.refresh_from_db()
    print(f"  New DB value: {group.profile_image_path}")
    assert group.profile_image_path == new_key, "DB not updated!"
else:
    print(f"✗ Commit failed: {response.json()}")
```

### Test 3: Rollback Image

```python
# Upload another image
img_io2 = io.BytesIO()
img.save(img_io2, format='PNG')
img_io2.seek(0)

response = client.post(
    f'/api/assets/upload?sponsor_type=group&sponsor_id={group.id}&role=profile_image',
    {'file': SimpleUploadedFile('test2.png', img_io2.getvalue(), content_type='image/png')},
    format='multipart'
)

new_key2 = response.json()['path']
print(f"Uploaded second image: {new_key2}")

# Get current DB value
current_db = group.profile_image_path
print(f"Current DB: {current_db}")

# Rollback (don't commit)
response = client.post(
    '/api/assets/rollback',
    {
        'new_key': new_key2,
        'sponsor_type': 'group',
        'sponsor_id': str(group.id),
        'role': 'profile_image'
    },
    content_type='application/json'
)

print(f"Rollback status: {response.status_code}")
if response.status_code == 200:
    print(f"✓ Rollback successful!")

    # Verify DB unchanged
    group.refresh_from_db()
    print(f"  DB still has: {group.profile_image_path}")
    assert group.profile_image_path == current_db, "DB changed unexpectedly!"
else:
    print(f"✗ Rollback failed: {response.json()}")
```

## Test with Celery

### Start Celery Worker

```bash
# In a separate terminal
celery -A mixtape worker -l info
```

### Watch Deletion Logs

After running commit or rollback, watch Celery logs for:

```
[INFO/MainProcess] Task assets.tasks.cleanup.delete_image_async[...] received
[INFO/ForkPoolWorker-1] [delete_image] Deleted image: groups/123/profile_image/old.jpg
[INFO/ForkPoolWorker-1] Task assets.tasks.cleanup.delete_image_async[...] succeeded
```

## Test with cURL

### Upload

```bash
# Create test image
convert -size 100x100 xc:red test.png

# Upload
curl -X POST \
  "http://localhost:8000/api/assets/upload?sponsor_type=group&sponsor_id=YOUR_GROUP_ID&role=profile_image" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -F "file=@test.png"

# Response:
# {
#   "path": "groups/123/profile_image/abc.jpg",
#   "url": "https://...",
#   "bytes": 12345,
#   "elapsed": 1.234
# }
```

### Commit

```bash
curl -X POST \
  "http://localhost:8000/api/assets/commit" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sponsor_type": "group",
    "sponsor_id": "YOUR_GROUP_ID",
    "role": "profile_image",
    "new_key": "groups/123/profile_image/abc.jpg",
    "old_key": "groups/123/profile_image/old.jpg"
  }'

# Response:
# {
#   "status": "committed",
#   "url": "https://...",
#   "path": "groups/123/profile_image/abc.jpg"
# }
```

### Rollback

```bash
curl -X POST \
  "http://localhost:8000/api/assets/rollback" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "new_key": "groups/123/profile_image/abc.jpg"
  }'

# Response:
# {
#   "status": "rolled_back"
# }
```

## Verify with Django Admin

1. Go to Django admin: `http://localhost:8000/admin/`
2. Find your group
3. Check `profile_image_path` field
4. Verify it changes after commit
5. Verify it doesn't change after rollback

## Check S3 Directly

```bash
# List images in S3
aws s3 ls s3://YOUR_BUCKET/groups/YOUR_GROUP_ID/profile_image/

# Verify image exists after upload
# Verify old image deleted after commit
# Verify new image deleted after rollback
```

## Expected Behaviors

### ✅ Upload
- Returns 201
- Image exists in S3
- DB unchanged

### ✅ Commit
- Returns 200
- DB updated to new key
- Old image deletion scheduled (check Celery logs)

### ✅ Rollback
- Returns 200
- DB unchanged
- New image deletion scheduled (check Celery logs)

### ✅ Permissions
- User can upload to their own profile
- User CANNOT upload to someone else's profile (403)
- Group members can upload to group (TODO: implement check)

## Troubleshooting

### Issue: 401 Unauthorized
**Fix:** Include valid JWT token in Authorization header

### Issue: 404 Sponsor not found
**Fix:** Verify group/user ID exists in database

### Issue: 400 Invalid image
**Fix:** Use PNG, JPEG, GIF, or WEBP format

### Issue: Images not deleted
**Fix:** Start Celery worker: `celery -A mixtape worker -l info`

### Issue: Permission denied
**Check:** Are you trying to upload to someone else's profile/group?

## Success Criteria

All these should work:
- [ ] Upload returns 201 with path and url
- [ ] S3 contains uploaded image
- [ ] DB unchanged after upload
- [ ] Commit updates DB
- [ ] Celery deletes old image
- [ ] Rollback keeps DB unchanged
- [ ] Celery deletes new image
- [ ] Invalid images rejected with 400
- [ ] Permission checks work

## Next: Frontend Integration

See `IMAGE-UPLOAD-ROLLBACK-IMPLEMENTATION.md` for:
- React/TypeScript code examples
- State management patterns
- Complete frontend flow
