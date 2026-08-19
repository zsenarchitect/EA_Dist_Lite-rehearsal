# Duck Desktop Pet

A charming desktop pet featuring a pixel art duck that brings joy to your screen! This application creates an interactive duck companion that can perform various activities and respond to user interactions.

## Features

- **Cute Pixel Art Duck**: Designed in Japanese cartoon style
- **Various Animations**:
  - Walking around screen
  - Chasing mouse occasionally
  - Sleeping in corner
  - Farming carrots
  - Reading books
  - Building duck house
  - Comic-style dialogue bubbles with jokes
  - "I'm bored" expressions
- **Interactive Features**:
  - Drag and drop interaction
  - Right-click menu with "Go Vacation" option
  - Text message conversations (OpenAI integration)
- **Sound Effects**: Cute sound effects for various actions
- **Animated GIFs**: Smooth animations for all activities

## Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

1. Run the application:
   ```bash
   python Pet.py
   ```

2. Interact with your duck:
   - Left-click and drag to move the duck
   - Right-click to open the menu
   - Watch it perform random activities
   - Chat with it using the text message interface

## OpenAI Integration

To enable the chat feature with OpenAI:
1. Obtain an OpenAI API key
2. Set it when initializing the chat:
   ```python
   chat_manager.set_api_key("your-api-key")
   ```

## Project Structure

```
Pet/
├── Pet.py              # Main entry script
├── duck_pet.py         # Main pet class
├── state_manager.py    # Activity state management
├── animations.py       # Animation handling
├── chat_manager.py     # Chat interface
├── requirements.txt    # Dependencies
├── README.md          # Documentation
└── assets/            # Resource files
    ├── animations/    # GIF animations
    ├── audio/        # Sound effects
    └── images/       # Static images
```

## Contributing

Feel free to contribute by:
1. Adding new animations
2. Creating new activities
3. Improving the AI chat responses
4. Enhancing the UI/UX

## License

This project is licensed under the MIT License - see the LICENSE file for details. 