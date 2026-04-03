# groups/permissions/decorators.py
"""
Decorator definitions for group permissions
"""

# Available membership decorators
MEMBERSHIP_DECORATORS = {
    'can__PostToStoryline': {
        'code': 'can__PostToStoryline',
        'name': 'Post to Storyline',
        'description': 'Create Storyline posts in this group',
        'category': 'capability',
    },
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
    'can__ManageThreadworks': {
        'code': 'can__ManageThreadworks',
        'name': 'Manage Threadworks',
        'description': 'Create, edit, and manage forums and discussions',
        'category': 'capability',
    },
    'can__ManageLanternmail': {
        'code': 'can__ManageLanternmail',
        'name': 'Manage Lanternmail',
        'description': 'Create, edit, and manage mailing lists',
        'category': 'capability',
    },
}


def get_available_decorators():
    """Get list of all available decorators"""
    return list(MEMBERSHIP_DECORATORS.values())
