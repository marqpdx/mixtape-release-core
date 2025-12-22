# groups/permissions/decorators.py
"""
Decorator definitions for group permissions
"""

# Available membership decorators
MEMBERSHIP_DECORATORS = {
    'can__ManageWriting': {
        'code': 'can__ManageWriting',
        'name': 'Manage Writing',
        'description': 'Create, edit, and manage writing pieces',
        'category': 'capability',
    },
    'can__ManageDispatch': {
        'code': 'can__ManageDispatch',
        'name': 'Manage Dispatch',
        'description': 'Create, edit, and manage dispatch documents',
        'category': 'capability',
    },
    'can__InviteMembers': {
        'code': 'can__InviteMembers',
        'name': 'Invite Members',
        'description': 'Send invitations to new members',
        'category': 'capability',
    },
    'can__CreateSponsoredCircle': {
        'code': 'can__CreateSponsoredCircle',
        'name': 'Create Sponsored Circle',
        'description': 'Can create a Circle sponsored by this Community',
        'category': 'capability',
    },
}


def get_available_decorators():
    """Get list of all available decorators"""
    return list(MEMBERSHIP_DECORATORS.values())
