# utils.py

import requests
from django.conf import settings
from typing import List, Dict, Any, Optional, Tuple

LISTMONK_BASE_URL = getattr(settings, 'LISTMONK_BASE_URL', 'http://localhost:9090/api')
LISTMONK_AUTH = getattr(settings, 'LISTMONK_AUTH', ('listmonk', 'listmonk'))


def validate_emails(emails: List[str]) -> List[str]:
    """Validate and clean email addresses"""
    valid_emails = []
    for email in emails:
        email = email.strip().lower()
        if '@' in email and len(email) > 0:
            valid_emails.append(email)
    return valid_emails


def create_new_subscriber(email: str, listmonk_list_id: int) -> bool:
    """Try to create a new subscriber with double opt-in"""
    subscriber_data = {
        'email': email,
        'name': email.split('@')[0],
        'status': 'enabled',
        'lists': [listmonk_list_id],
        'preconfirm_subscriptions': False  # Triggers double opt-in
    }

    print(f"📧 Attempting to create subscriber: {email}")

    try:
        r = requests.post(
            f"{LISTMONK_BASE_URL}/subscribers",
            json=subscriber_data,
            auth=LISTMONK_AUTH,
            timeout=10,
        )

        print(f"📧 Create response for {email}: {r.status_code}")

        if r.status_code in [200, 201]:
            print(f"✅ Created new subscriber: {email}")
            return True

        return False

    except requests.RequestException as e:
        print(f"❌ Error creating subscriber {email}: {e}")
        return False


# def find_existing_subscriber(email: str) -> Optional[Dict[str, Any]]:
#     """Find an existing subscriber by email"""
#     try:
#         search_response = requests.get(
#             f"{LISTMONK_BASE_URL}/subscribers",
#             auth=LISTMONK_AUTH,
#             timeout=10,
#         )

#         print(f"🔍 Search response status: {search_response.status_code}")

#         if search_response.ok:
#             search_data = search_response.json()
#             subscribers = search_data.get('data', {}).get('results', [])
#             return next((s for s in subscribers if s['email'].lower() == email.lower()), None)

#         return None

#     except requests.RequestException as e:
#         print(f"❌ Error searching for subscriber {email}: {e}")
#         return None


def find_existing_subscriber(email: str) -> Optional[Dict[str, Any]]:
    """Find an existing subscriber by email using proper search"""
    try:
        # Use the query parameter correctly
        search_response = requests.get(
            f"{LISTMONK_BASE_URL}/subscribers",
            params={
                'query': email,  # Use the query parameter
                'per_page': 1
            },
            auth=LISTMONK_AUTH,
            timeout=10,
        )

        print(f"🔍 Search response status: {search_response.status_code}")

        if search_response.ok:
            search_data = search_response.json()
            subscribers = search_data.get('data', {}).get('results', [])
            # Should find exact match since we searched for the email
            return next((s for s in subscribers if s['email'].lower() == email.lower()), None)

        return None

    except requests.RequestException as e:
        print(f"❌ Error searching for subscriber {email}: {e}")
        return None



def check_list_subscription(user_lists: List[Dict], listmonk_list_id: int) -> Tuple[bool, Optional[str]]:
    """Check if user is already subscribed to a specific list"""
    existing_subscription = next((lst for lst in user_lists if lst['id'] == listmonk_list_id), None)

    if existing_subscription:
        subscription_status = existing_subscription.get('subscription_status', 'unknown')
        return True, subscription_status

    return False, None


def add_subscriber_to_list(subscriber_id: int, listmonk_list_id: int) -> bool:
    """Add an existing subscriber to a list in unconfirmed status"""
    try:
        subscribe_response = requests.put(
            f"{LISTMONK_BASE_URL}/subscribers/lists",
            json={
                'ids': [subscriber_id],
                'action': 'add',
                'target_list_ids': [listmonk_list_id],
                'status': 'unconfirmed'  # This creates the subscription record
            },
            auth=LISTMONK_AUTH,
            timeout=10,
        )

        print(f"📧 Subscribe response: {subscribe_response.status_code}")

        if subscribe_response.ok:
            print(f"✅ Added subscriber {subscriber_id} to list {listmonk_list_id}")
            return True
        else:
            print(f"❌ Failed to add subscriber to list: {subscribe_response.text}")
            return False

    except requests.RequestException as e:
        print(f"❌ Error adding subscriber to list: {e}")
        return False


def send_invitation_email(email: str, subscriber_uuid: str, listmonk_list_id: int, listmonk_list_uuid: str, list_name: str) -> bool:
    """Send transactional invitation email"""
    try:

        optin_url = f"http://localhost:9090/subscription/optin/{subscriber_uuid}?l={listmonk_list_uuid}"

        tx_response = requests.post(
            f"{LISTMONK_BASE_URL}/tx",
            json={
                'subscriber_email': email,
                'template_id': 5,  # Your invitation template ID
                'data': {
                    'list_name': list_name,
                    'inviter_name': 'Mixtape Team',
                    'optin_url': optin_url,
                },
                'content_type': 'html'
            },
            auth=LISTMONK_AUTH,
            timeout=10,
        )

        print(f"📧 Transactional email response: {tx_response.status_code}")
        print(f"📧 Using optin URL: {optin_url}")

        if tx_response.ok:
            print(f"✅ Sent invitation email to: {email}")
            return True
        else:
            print(f"❌ Failed to send invitation email: {tx_response.text}")
            return False

    except requests.RequestException as e:
        print(f"❌ Error sending invitation email: {e}")
        return False


def handle_existing_subscriber(email: str, listmonk_list_id: int, listmonk_list_uuid: str, list_name: str) -> Tuple[bool, str]:
    """Handle invitation for an existing subscriber"""
    existing_user = find_existing_subscriber(email)

    if not existing_user:
        return False, "User exists but couldn't find in search"

    subscriber_id = existing_user['id']
    subscriber_uuid = existing_user['uuid']
    user_lists = existing_user.get('lists', [])

    print(f"✅ Found existing user ID: {subscriber_id}, UUID: {subscriber_uuid}")

    # Check if already subscribed to this specific list
    is_subscribed, subscription_status = check_list_subscription(user_lists, listmonk_list_id)

    if is_subscribed:
        print(f"📧 User {email} already has subscription to list {listmonk_list_id}: {subscription_status}")

        if subscription_status == 'confirmed':
            print(f"✅ User {email} already confirmed on list {listmonk_list_id}")
            return True, "Already confirmed"

        elif subscription_status in ['unconfirmed', 'pending']:
            print(f"📧 User {email} already pending on list {listmonk_list_id}, resending invitation...")
            success = send_invitation_email(email, subscriber_uuid, listmonk_list_id, listmonk_list_uuid, list_name)
            return success, "Resent invitation to pending user"

        else:  # unsubscribed
            print(f"📧 User {email} was unsubscribed from list {listmonk_list_id}, re-inviting...")
            # Add back to list and send email
            if add_subscriber_to_list(subscriber_id, listmonk_list_id):
                success = send_invitation_email(email, subscriber_uuid, listmonk_list_id, listmonk_list_uuid, list_name)
                return success, "Re-invited unsubscribed user"
            else:
                return False, "Failed to re-add unsubscribed user to list"

    else:
        print(f"📧 User {email} not on list {listmonk_list_id}, adding them...")

        # Add to list and send invitation
        if add_subscriber_to_list(subscriber_id, listmonk_list_id):
            success = send_invitation_email(email, subscriber_uuid, listmonk_list_id, listmonk_list_uuid, list_name)
            return success, "Added to list and sent invitation"
        else:
            return False, "Failed to add user to list"


def process_single_email(email: str, listmonk_list_id: int, listmonk_list_uuid: str, list_name: str) -> Tuple[bool, str]:
    """Process a single email invitation"""
    try:
        # Try to create new subscriber first
        if create_new_subscriber(email, listmonk_list_id):
            return True, "Created new subscriber"

        # If creation failed, check if user already exists (409 error)
        print(f"👤 User {email} might already exist, checking...")
        return handle_existing_subscriber(email, listmonk_list_id, listmonk_list_uuid, list_name)

    except requests.RequestException as e:
        error_msg = f"Network error processing {email}: {str(e)}"
        print(f"❌ {error_msg}")
        return False, error_msg


def send_listmonk_invitations(listmonk_list_id: int, listmonk_list_uuid: str, emails: List[str], list_name: str = "Our Mailing List") -> Dict[str, Any]:
    """
    Send double opt-in invitations via ListMonk

    Args:
        listmonk_list_id: The ListMonk list ID (not Django ID)
        emails: List of email addresses to invite
        list_name: Human-readable name of the list for emails

    Returns:
        Dict with success status and details
    """
    if not emails:
        return {"success": False, "error": "No email addresses provided"}

    # Validate emails
    valid_emails = validate_emails(emails)
    if not valid_emails:
        return {"success": False, "error": "No valid email addresses found"}

    print(f"📧 Sending invitations to {len(valid_emails)} emails for ListMonk list {listmonk_list_id}")

    successful_emails = []
    failed_emails = []

    # Process each email
    for email in valid_emails:
        success, message = process_single_email(email, listmonk_list_id, listmonk_list_uuid, list_name)

        if success:
            successful_emails.append(email)
            print(f"✅ Successfully processed {email}: {message}")
        else:
            failed_emails.append({"email": email, "error": message})
            print(f"❌ Failed to process {email}: {message}")

    # Return results
    if successful_emails:
        return {
            "success": True,
            "invited_count": len(successful_emails),
            "emails": successful_emails,
            "failed": failed_emails
        }
    else:
        return {
            "success": False,
            "error": "All invitations failed",
            "failed": failed_emails
        }

