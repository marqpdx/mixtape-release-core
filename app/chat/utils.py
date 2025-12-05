# chat/utils.py

MENTIONABLE_TYPES = {
    "user": "auth.User",  # Individual members
    "group": "groups.Group",  # Groups (notifications go to stewards/founders)
}

# Helper function to get mentionable objects
def get_mentionable_objects_for_conversation(conversation, query=""):
    """Get users and groups that can be mentioned in this conversation"""
    mentionables = []

    # Users in conversation
    participants = conversation.participants.select_related("user").all()
    for participant in participants:
        if query.lower() in participant.user.username.lower():
            mentionables.append({
                "type": "user",
                "id": participant.user.id,
                "display": f"@{participant.user.username}",
                "name": participant.user.get_full_name() or participant.user.username
            })

    # Groups (if conversation is within a group context)
    # Add your group logic here based on conversation context

    return mentionables


def generate_conversation_title(participants_usernames, current_user):
    """Generate title with multiple fallback strategies"""
    other_participants = [u for u in participants_usernames if u != current_user.username]

    if len(other_participants) == 1:
        return f"Chat with {other_participants[0]}"
    if len(other_participants) <= 4:
        # For small groups, try to list names (with length limit)
        names_str = ", ".join(other_participants)
        if len(names_str) <= 40:  # Reasonable title length
            return f"Chat: {names_str}"
        return f"Group chat ({len(participants_usernames)} members)"
    return f"Group chat ({len(participants_usernames)} members)"
