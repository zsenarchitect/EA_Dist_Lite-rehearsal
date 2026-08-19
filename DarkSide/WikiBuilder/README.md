# WikiBuilder

A minimalist wiki generator for EnneadTab knowledge base with clean, modern design and earthy color palette.

## Features

- 🌿 **Minimalist Design**: Clean, elegant interface with earthy color palette
- 📱 **Responsive Layout**: Works perfectly on desktop, tablet, and mobile
- 🔍 **Search Functionality**: Real-time search across all tools and descriptions
- 📋 **Sidebar Navigation**: Easy navigation by tool categories
- 📊 **Statistics Dashboard**: Overview of available tools and popular items
- 🎨 **Consistent Styling**: Unified design language across all pages
- 📅 **Dynamic Year**: Always shows current year in footer
- ⬆️ **Back to Top**: Smooth scrolling navigation

## Color Palette

The design uses a calming, earthy color scheme:

- **Primary**: Warm brown (`#8B7355`)
- **Secondary**: Sienna (`#A0522D`)
- **Accent**: Tan (`#D2B48C`)
- **Background**: Beige (`#F5F5DC`)
- **Text**: Dark gray (`#2F2F2F`)
- **Text Light**: Medium gray (`#6B6B6B`)

## Usage

### Simple Usage

```python
from WikiBuilder import generate_wiki

# Generate the complete wiki website
success = generate_wiki(
    wiki_repo_path="path/to/wiki/repo",
    rhino_data_file="path/to/rhino/knowledge.json",
    revit_data_file="path/to/revit/knowledge.json"
)
```

### Advanced Usage

```python
from WikiBuilder.wiki_generator import WikiGenerator

# Create a custom generator instance
generator = WikiGenerator("path/to/wiki/repo")

# Generate the wiki with custom data files
success = generator.generate(
    rhino_data_file="path/to/rhino/knowledge.json",
    revit_data_file="path/to/revit/knowledge.json"
)
```

## Generated Pages

The WikiBuilder generates three main pages:

1. **index.html** - Landing page with statistics and platform navigation
2. **rhino.html** - Rhino tools organized by category with search
3. **revit.html** - Revit tools organized by category with search

## Integration with Publish Script

The WikiBuilder is integrated into the main publish script (`________publish.py`) and is called automatically during the publishing process. The old wiki generation methods have been replaced with a simple call to the WikiBuilder module.

## Design Philosophy

- **Minimalism**: Clean, uncluttered interface focusing on content
- **Elegance**: Sophisticated typography and spacing
- **Accessibility**: High contrast and readable fonts
- **Performance**: Lightweight CSS and efficient JavaScript
- **Consistency**: Unified design language across all pages

## File Structure

```
WikiBuilder/
├── __init__.py          # Main module interface
├── wiki_generator.py    # Core generation logic
└── README.md           # This documentation
```

## Requirements

- Python 3.6+
- JSON knowledge data files
- Git repository for wiki deployment

## License

Part of the EnneadTab project. See main repository for license information. 