"""Small, bundled line-icon vocabulary. No remote assets or arbitrary SVG input."""
ICONS = {
    'receipt': ('Receipt', '<path d="M5 3l2 2 2-2 3 2 3-2 2 2 2-2v18l-2-2-2 2-3-2-3 2-2-2-2 2zM9 9h6M9 13h6"/>'),
    'bolt': ('Electricity', '<path d="M13 2L4 14h7l-1 8 10-13h-8z"/>'),
    'wifi': ('Internet', '<path d="M2 8a16 16 0 0 1 20 0M5 12a11 11 0 0 1 14 0M8 16a6 6 0 0 1 8 0"/><circle cx="12" cy="20" r="1"/>'),
    'home': ('Housing', '<path d="M3 10l9-7 9 7v11H3zM9 21v-8h6v8"/>'),
    'credit-card': ('Credit card', '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 10h18M7 15h3"/>'),
    'wallet': ('Income / wallet', '<path d="M20 7V4H5a2 2 0 0 0 0 4h16v12H5a2 2 0 0 1-2-2V6M21 12h-6v4h6"/>'),
    'shield': ('Insurance', '<path d="M12 3l8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6"/>'),
    'droplet': ('Water', '<path d="M12 2S5 10 5 15a7 7 0 0 0 14 0c0-5-7-13-7-13z"/>'),
    'flame': ('Gas / heating', '<path d="M12 2c2 6 7 7 7 13a7 7 0 0 1-14 0c0-3 2-5 4-7 0 4 2 5 3 5 3-4 0-11 0-11z"/>'),
    'phone': ('Phone', '<rect x="7" y="2" width="10" height="20" rx="2"/><path d="M10 18h4"/>'),
    'car': ('Transport', '<path d="M3 11l3-6h12l3 6v7H3zM3 11h18M6 18v3M18 18v3M6 14h2M16 14h2"/>'),
    'heart': ('Health', '<path d="M12 21L4 13C-3 5 7-1 12 6c5-7 15-1 8 7z"/>'),
    'bag': ('Shopping', '<path d="M4 7h16l1 14H3zM8 7V6a4 4 0 0 1 8 0v1"/>'),
    'cart': ('Groceries', '<path d="M2 3h3l3 12h11l3-8H6"/><circle cx="9" cy="20" r="1"/><circle cx="18" cy="20" r="1"/>'),
    'coffee': ('Food / coffee', '<path d="M4 8h12v7a6 6 0 0 1-12 0zM16 8h2a3 3 0 0 1 0 6h-2M3 22h15M7 2v3M12 2v3"/>'),
    'tv': ('Subscriptions / TV', '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M7 2l5 5 5-5"/>'),
    'music': ('Music', '<path d="M9 18V5l12-3v14M9 9l12-3"/><ellipse cx="6" cy="18" rx="3" ry="2"/><ellipse cx="18" cy="16" rx="3" ry="2"/>'),
    'book': ('Education', '<path d="M12 5C8 2 4 3 2 4v16c3-2 7-2 10 0 3-2 7-2 10 0V4c-2-1-6-2-10 1v15"/>'),
    'gift': ('Gifts', '<path d="M3 8h18v5H3zM5 13v8h14v-8M12 8v13"/><path d="M12 8C1 8 6-3 12 8c6-11 11 0 0 0z"/>'),
    'briefcase': ('Work', '<rect x="3" y="7" width="18" height="14" rx="2"/><path d="M8 7V3h8v4M3 12h18M10 12v3h4v-3"/>'),
    'building': ('Bank / taxes', '<path d="M2 9l10-6 10 6zM4 21h16M6 12v6M12 12v6M18 12v6"/>'),
    'repeat': ('Recurring', '<path d="M3 10V6h15l-3-3M21 14v4H6l3 3M18 6l-3 3M6 18l3-3"/>'),
    'calendar': ('Calendar', '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 2v6M17 2v6M3 11h18M7 15h2M15 15h2"/>'),
    'tag': ('Category', '<path d="M3 3h8l10 10-8 8L3 11z"/><circle cx="7" cy="7" r="1"/>'),
    'check': ('Complete', '<path d="M5 12l4 4L19 6"/>'),
    'checks': ('PayBillz', '<path d="M2 12l4 4L16 6M12 15l3 3L23 8"/>'),
    'plus': ('Add', '<path d="M12 5v14M5 12h14"/>'),
    'history': ('History', '<path d="M3 11a9 9 0 1 1 2 7M3 4v7h7M12 7v6l4 2"/>'),
    'arrows': ('Transactions', '<path d="M3 7h18l-4-4M21 17H3l4 4"/>'),
    'edit': ('Edit', '<path d="M4 16L16 4l4 4L8 20H4zM14 6l4 4"/>'),
    'chevron-left': ('Previous', '<path d="M15 5l-7 7 7 7"/>'),
    'chevron-right': ('Next', '<path d="M9 5l7 7-7 7"/>'),
    'close': ('Close', '<path d="M6 6l12 12M6 18L18 6"/>'),
}
ICON_CHOICES = [(key, label) for key, (label, _) in ICONS.items() if key not in {'checks','plus','history','arrows','edit','chevron-left','chevron-right','close'}]

def suggested_icon(name, subcategory=''):
    text = f'{subcategory} {name}'.lower()
    for keywords, icon in [('electric power','bolt'), ('internet wifi broadband','wifi'), ('water sewer','droplet'), ('gas heating','flame'), ('phone mobile cellular','phone'), ('credit visa mastercard card','credit-card'), ('rent mortgage housing home','home'), ('insurance','shield'), ('income salary paycheck wages','wallet'), ('auto car transport','car'), ('health medical','heart'), ('subscription streaming','tv'), ('grocery groceries','cart')]:
        if any(word in text.split() for word in keywords.split()):
            return icon
    return 'receipt'
