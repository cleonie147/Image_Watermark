"""
=====================================================================
 BULK IMAGE WATERMARKING AND DATABASE MANAGEMENT SYSTEM
=====================================================================
This is an upgraded version of the original "Simple Bulk Image
Watermarker" script. The original watermarking logic (diagonal,
centered, semi-transparent watermark that gets flattened into the
image) is kept almost exactly the same.

NEW in this version:
  - A SQLite database (watermark.db) that records every image that
    gets processed: filename, watermark text, font size, opacity,
    input/output paths, the date and time it was processed, and
    whether it succeeded or failed.
  - A simple text menu so the program can be used interactively:
      1. Watermark all images
      2. View processing history
      3. Search history by image filename
      4. Delete a history record by ID (only the DB row, never the
         actual image file)
      5. Exit
  - Basic error handling for missing folders, unsupported files,
    and any image that fails to process.
  - CUSTOMIZABLE WATERMARK: before watermarking a batch, the program
    now asks the user to pick the watermark text (from a preset list
    or their own custom text), the font size, and the opacity, and
    shows a confirmation screen before touching any images. Whatever
    the user chooses is applied to every image in that batch and is
    also saved into the database alongside each image's history row.

Only libraries needed: Pillow (PIL) and sqlite3 (sqlite3 is built
into Python, so you do NOT need to install it separately).

Install Pillow with:  pip install pillow
=====================================================================
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------
# SETTINGS - CHANGE THESE PATHS TO MATCH YOUR OWN COMPUTER
# ---------------------------------------------------------------
# PLACEHOLDER: replace the text inside the quotes with the real
# folder paths on your machine before running the program.
INPUT_FOLDER = Path(r"Input")     # e.g. r"C:\Users\<you>\...\input_images"
OUTPUT_FOLDER = Path(r"Output")   # e.g. r"C:\Users\<you>\...\output_images"

# These three are now just DEFAULT / FALLBACK values. The actual values
# used for a batch are collected from the user through get_watermark_settings()
# every time "Watermark all images" is chosen from the menu.
DEFAULT_WATERMARK_TEXT = "CONFIDENTIAL"  # the text stamped onto each image
DEFAULT_FONT_SIZE = 60                   # size of the watermark text
DEFAULT_OPACITY = 90                     # 0 = invisible, 255 = fully solid (out of 255)

# A few ready-made watermark texts the user can pick by number instead of typing.
PRESET_WATERMARKS = ["CONFIDENTIAL", "COPYRIGHT", "DRAFT", "SAMPLE", "DO NOT COPY"]

# The database file will be created in the same folder as this script.
DB_FILE = Path(__file__).parent / "watermark.db"

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png")


# =====================================================================
# SECTION 1: DATABASE FUNCTIONS
# =====================================================================
# All database work goes through these functions. Every SQL query
# uses "?" placeholders (parameterized queries) instead of joining
# text together, which is the standard way to prevent SQL injection.

def init_database():
    """
    Connects to watermark.db (creating the file if it doesn't exist)
    and makes sure the watermark_history table exists.
    """
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS watermark_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_filename TEXT NOT NULL,
            watermark_text TEXT NOT NULL,
            font_size INTEGER NOT NULL,
            opacity INTEGER NOT NULL,
            input_path TEXT NOT NULL,
            output_path TEXT NOT NULL,
            processed_datetime TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)
    connection.commit()
    connection.close()


def log_history(image_filename, watermark_text, font_size, opacity, input_path, output_path, status):
    """
    Inserts one row into watermark_history. Called once per image,
    whether the watermarking succeeded or failed, so the table also
    works as an error log. font_size and opacity are the exact
    settings the user chose for this batch, so every row shows
    exactly how that image was watermarked.
    """
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    processed_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO watermark_history
            (image_filename, watermark_text, font_size, opacity, input_path, output_path, processed_datetime, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (image_filename, watermark_text, font_size, opacity, str(input_path), str(output_path),
          processed_datetime, status))

    connection.commit()
    connection.close()


def view_all_history():
    """Fetches and prints every row in watermark_history, newest first."""
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute("SELECT id, image_filename, watermark_text, font_size, opacity, processed_datetime, status "
                    "FROM watermark_history ORDER BY id DESC")
    rows = cursor.fetchall()
    connection.close()

    if not rows:
        print("\nNo history records found yet.\n")
        return

    print("\n" + "-" * 105)
    print(f"{'ID':<5}{'Filename':<20}{'Watermark':<15}{'Font':<6}{'Opacity':<9}{'Processed At':<20}{'Status':<15}")
    print("-" * 105)
    for row in rows:
        record_id, filename, watermark_text, font_size, opacity, processed_datetime, status = row
        print(f"{record_id:<5}{filename:<20}{watermark_text:<15}{font_size:<6}{opacity:<9}{processed_datetime:<20}{status:<15}")
    print("-" * 105 + "\n")


def search_history_by_filename(search_text):
    """
    Looks for any filename that CONTAINS search_text (case-insensitive).
    Uses a parameterized LIKE query, so the search text is always
    treated as data, never as part of the SQL command itself.
    """
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute("""
        SELECT id, image_filename, watermark_text, font_size, opacity, processed_datetime, status
        FROM watermark_history
        WHERE image_filename LIKE ?
        ORDER BY id DESC
    """, (f"%{search_text}%",))
    rows = cursor.fetchall()
    connection.close()

    if not rows:
        print(f"\nNo history records found matching '{search_text}'.\n")
        return

    print("\n" + "-" * 105)
    print(f"{'ID':<5}{'Filename':<20}{'Watermark':<15}{'Font':<6}{'Opacity':<9}{'Processed At':<20}{'Status':<15}")
    print("-" * 105)
    for row in rows:
        record_id, filename, watermark_text, font_size, opacity, processed_datetime, status = row
        print(f"{record_id:<5}{filename:<20}{watermark_text:<15}{font_size:<6}{opacity:<9}{processed_datetime:<20}{status:<15}")
    print("-" * 105 + "\n")


def delete_history_record(record_id):
    """
    Deletes ONE row from watermark_history by its id.
    This only removes the database record - the actual image files
    in the output folder are never touched.
    """
    connection = sqlite3.connect(DB_FILE)
    cursor = connection.cursor()
    cursor.execute("SELECT id FROM watermark_history WHERE id = ?", (record_id,))
    existing = cursor.fetchone()

    if existing is None:
        print(f"\nNo history record found with ID {record_id}.\n")
        connection.close()
        return

    cursor.execute("DELETE FROM watermark_history WHERE id = ?", (record_id,))
    connection.commit()
    connection.close()
    print(f"\nHistory record with ID {record_id} was deleted (image file was NOT touched).\n")


# =====================================================================
# SECTION 2: WATERMARKING FUNCTIONS (same logic as the original script)
# =====================================================================

def make_watermark_layer(text, font_size, opacity, image_width, image_height):
    """
    Builds one transparent "sheet" the same size as the photo,
    with the watermark text drawn diagonally through the center.
    We build it separately first so it's easy to rotate before
    placing it on top of the real photo.
    """
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except IOError:
        font = ImageFont.load_default()

    # Step A: draw the watermark text onto its OWN small transparent image first.
    temp_image = Image.new("RGBA", (1, 1))
    temp_draw = ImageDraw.Draw(temp_image)
    text_box = temp_draw.textbbox((0, 0), text, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]

    text_layer = Image.new("RGBA", (text_width + 20, text_height + 20), (255, 255, 255, 0))
    text_draw = ImageDraw.Draw(text_layer)
    text_draw.text((10, 10), text, font=font, fill=(255, 255, 255, opacity))

    # Step B: rotate the text so it runs diagonally (like a classic watermark).
    rotated_text = text_layer.rotate(45, expand=True)

    # Step C: create a full-size transparent sheet matching the photo,
    # and paste the rotated text into the exact CENTER of it.
    full_layer = Image.new("RGBA", (image_width, image_height), (255, 255, 255, 0))
    paste_x = (image_width - rotated_text.width) // 2
    paste_y = (image_height - rotated_text.height) // 2
    full_layer.paste(rotated_text, (paste_x, paste_y), mask=rotated_text)

    return full_layer


def watermark_single_image(file_path, watermark_text, font_size, opacity):
    """
    Watermarks one image file and saves it to OUTPUT_FOLDER, using
    whatever watermark_text, font_size, and opacity were chosen by
    the user for this batch.
    Returns the output_path so the caller can log the result to the
    database.
    PNG files are saved as PNG, and JPG/JPEG files are saved as JPEG,
    matching the original file's format.
    """
    file_extension = file_path.suffix.lower()
    output_path = OUTPUT_FOLDER / file_path.name

    original_image = Image.open(file_path).convert("RGBA")
    image_width, image_height = original_image.size

    watermark_sheet = make_watermark_layer(
        watermark_text, font_size, opacity, image_width, image_height
    )

    combined_image = Image.alpha_composite(original_image, watermark_sheet)

    if file_extension == ".png":
        # Keep transparency support and save as PNG.
        combined_image.save(output_path, format="PNG")
    else:
        # JPG/JPEG cannot store transparency, so flatten to RGB first.
        final_image = combined_image.convert("RGB")
        final_image.save(output_path, format="JPEG")

    return output_path


def watermark_all_images(watermark_text, font_size, opacity):
    """
    Goes through every file in INPUT_FOLDER, watermarks the supported
    ones using the given watermark_text/font_size/opacity, and logs
    one history row per file (success or failure), including those
    same settings. Handles a missing input folder and
    unsupported/broken files without crashing the whole program.
    """
    if not INPUT_FOLDER.exists():
        print(f"\nERROR: Input folder does not exist:\n  {INPUT_FOLDER}")
        print("Please create it (or fix the INPUT_FOLDER path at the top of the script) and try again.\n")
        return

    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    files = sorted(INPUT_FOLDER.iterdir())
    if not files:
        print(f"\nNo files found in input folder: {INPUT_FOLDER}\n")
        return

    processed_count = 0
    failed_count = 0

    for file_path in files:
        if not file_path.is_file():
            continue

        file_extension = file_path.suffix.lower()

        if file_extension not in SUPPORTED_EXTENSIONS:
            print(f"Skipping (unsupported file type): {file_path.name}")
            log_history(file_path.name, watermark_text, font_size, opacity, file_path, "N/A",
                        "Skipped - Unsupported Type")
            continue

        try:
            print(f"Watermarking: {file_path.name}")
            output_path = watermark_single_image(file_path, watermark_text, font_size, opacity)
            log_history(file_path.name, watermark_text, font_size, opacity, file_path, output_path, "Success")
            processed_count += 1

        except Exception as error:
            # Catches any image-processing failure (corrupt file, permission
            # error, etc.) so one bad image doesn't stop the whole batch.
            print(f"FAILED to watermark {file_path.name}: {error}")
            log_history(file_path.name, watermark_text, font_size, opacity, file_path, "N/A",
                        f"Failed - {error}")
            failed_count += 1

    print(f"\nDone. {processed_count} image(s) watermarked successfully, {failed_count} failed.")
    print(f"Check the output folder: {OUTPUT_FOLDER}\n")


# =====================================================================
# SECTION 2B: CUSTOM WATERMARK SETTINGS MENU
# =====================================================================
# This section asks the user what watermark they want BEFORE any
# image is touched. It always returns three plain values:
# (watermark_text, font_size, opacity), or None if the user backs out
# at the confirmation step.

def choose_watermark_text():
    """
    Lets the user either pick one of the PRESET_WATERMARKS by number,
    or type their own custom text. Keeps asking until it gets a
    non-empty answer.
    """
    print("\nStep 1: Choose the watermark text.")
    print("Preset options:")
    for index, preset in enumerate(PRESET_WATERMARKS, start=1):
        print(f"  {index}. {preset}")
    print(f"  {len(PRESET_WATERMARKS) + 1}. Enter my own custom text")

    while True:
        choice = input("Enter a number from the list above: ").strip()

        if choice.isdigit():
            choice_number = int(choice)

            # A number that matches one of the presets.
            if 1 <= choice_number <= len(PRESET_WATERMARKS):
                return PRESET_WATERMARKS[choice_number - 1]

            # The "custom text" option.
            if choice_number == len(PRESET_WATERMARKS) + 1:
                custom_text = input("Type your custom watermark text: ").strip()
                if custom_text:
                    return custom_text
                print("Watermark text cannot be empty. Please try again.")
                continue

        print("Invalid choice. Please enter a valid number from the list.")


def choose_font_size():
    """
    Asks the user for a font size. Pressing Enter with nothing typed
    keeps the sensible default. Keeps asking until it gets a positive
    whole number.
    """
    print(f"\nStep 2: Choose the font size (default is {DEFAULT_FONT_SIZE}).")
    while True:
        text = input(f"Enter font size, or press Enter for default [{DEFAULT_FONT_SIZE}]: ").strip()

        if text == "":
            return DEFAULT_FONT_SIZE

        if text.isdigit() and int(text) > 0:
            return int(text)

        print("Please enter a whole number greater than 0 (e.g. 40, 60, 80).")


def choose_opacity():
    """
    Asks the user for an opacity value between 0 and 255.
    Pressing Enter with nothing typed keeps the sensible default.
    Keeps asking until the value is validated as a whole number in
    the 0-255 range (0 = invisible, 255 = fully solid).
    """
    print(f"\nStep 3: Choose the opacity, 0-255 (default is {DEFAULT_OPACITY}).")
    print("  0   = watermark is invisible")
    print("  255 = watermark is fully solid")
    while True:
        text = input(f"Enter opacity (0-255), or press Enter for default [{DEFAULT_OPACITY}]: ").strip()

        if text == "":
            return DEFAULT_OPACITY

        if text.isdigit() and 0 <= int(text) <= 255:
            return int(text)

        print("Please enter a whole number between 0 and 255.")


def get_watermark_settings():
    """
    Runs the full customization flow: text -> font size -> opacity ->
    confirmation. Returns (watermark_text, font_size, opacity) if the
    user confirms, or None if the user chooses not to proceed.
    """
    watermark_text = choose_watermark_text()
    font_size = choose_font_size()
    opacity = choose_opacity()

    print("\n" + "=" * 50)
    print(" CONFIRM YOUR WATERMARK SETTINGS")
    print("=" * 50)
    print(f"  Watermark text : {watermark_text}")
    print(f"  Font size      : {font_size}")
    print(f"  Opacity        : {opacity} (out of 255)")
    print("=" * 50)

    confirm = input("Apply these settings to ALL images in the input folder? (y/n): ").strip().lower()

    if confirm == "y":
        return watermark_text, font_size, opacity

    print("\nCancelled. No images were processed.\n")
    return None


# =====================================================================
# SECTION 3: MENU / MAIN PROGRAM
# =====================================================================

def show_menu():
    print("=" * 50)
    print(" BULK IMAGE WATERMARKING & DATABASE SYSTEM")
    print("=" * 50)
    print("1. Watermark all images")
    print("2. View processing history")
    print("3. Search history by image filename")
    print("4. Delete a history record by ID")
    print("5. Exit")
    print("=" * 50)


def main():
    init_database()

    while True:
        show_menu()
        choice = input("Enter your choice (1-5): ").strip()

        if choice == "1":
            settings = get_watermark_settings()
            if settings is not None:
                watermark_text, font_size, opacity = settings
                watermark_all_images(watermark_text, font_size, opacity)

        elif choice == "2":
            view_all_history()

        elif choice == "3":
            search_text = input("Enter filename (or part of it) to search: ").strip()
            search_history_by_filename(search_text)

        elif choice == "4":
            id_text = input("Enter the ID of the history record to delete: ").strip()
            if id_text.isdigit():
                delete_history_record(int(id_text))
            else:
                print("\nPlease enter a valid whole number ID.\n")

        elif choice == "5":
            print("\nExiting program. Goodbye!")
            break

        else:
            print("\nInvalid choice. Please enter a number from 1 to 5.\n")


if __name__ == "__main__":
    main()