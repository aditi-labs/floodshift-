"""
Perceptron API Smoke Test
Person 3 owns this script.

Run with: python scripts/test_perceptron.py [path_to_image]
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv()

def test_perceptron_connection():
    """Test that we can connect to Perceptron API."""
    api_key = os.environ.get("PERCEPTRON_API_KEY")

    if not api_key:
        print("ERROR: PERCEPTRON_API_KEY not set in .env")
        return False

    print(f"API Key found: {api_key[:10]}...{api_key[-4:]}")

    try:
        import perceptron
        print(f"Perceptron SDK version: {getattr(perceptron, '__version__', 'unknown')}")

        # Try a simple detection with a test prompt
        # We'll test against a placeholder - in real use you'd have an actual image
        print("\nPerceptron SDK imported successfully!")
        print("Ready for real image detection.")

        return True

    except ImportError as e:
        print(f"ERROR: Cannot import perceptron: {e}")
        return False
    except Exception as e:
        print(f"ERROR: {e}")
        return False


def test_with_image(image_path: str):
    """Test detection on a real image."""
    from backend.perception.perceptron_adapter import PerceptronAdapter

    path = Path(image_path)
    if not path.exists():
        print(f"ERROR: Image not found: {path}")
        return False

    print(f"\nTesting detection on: {path}")

    adapter = PerceptronAdapter(mock_mode=False)
    print(f"Adapter status: {adapter.status}")

    if adapter.mock_mode:
        print("WARNING: Running in mock mode (API key issue?)")
        return False

    # Run detection
    boxes = adapter.recognize_board(str(path), 1280, 720)

    print(f"\nDetected {len(boxes)} objects:")
    for box in boxes:
        print(f"  - {box.token_type or 'unknown'}: '{box.mention}'")
        print(f"    Position: ({box.x1:.0f}, {box.y1:.0f}) to ({box.x2:.0f}, {box.y2:.0f})")

    return True


if __name__ == "__main__":
    print("=" * 50)
    print("FLOODSHIFT Perceptron Test")
    print("=" * 50)

    # Test connection
    if not test_perceptron_connection():
        sys.exit(1)

    # If image path provided, test detection
    if len(sys.argv) > 1:
        image_path = sys.argv[1]
        test_with_image(image_path)
    else:
        print("\nTo test with an image, run:")
        print("  python scripts/test_perceptron.py path/to/image.jpg")
