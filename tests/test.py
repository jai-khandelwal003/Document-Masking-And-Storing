import os
import requests
import csv
import base64

# Configure these variables
API_URL = "http://localhost:3000/mask/aadhar"  # Replace with the correct API URL
IMAGE_DIR = "./test-images"  # Directory containing the images
MASKED_IMAGE_DIR = "./masked_images"  # Directory to save masked images
CSV_OUTPUT = "output.csv"  # Path to save the CSV file

# Ensure output directories exist
os.makedirs(MASKED_IMAGE_DIR, exist_ok=True)

# Headers for the API
HEADERS = {
    "last4Mask": "false",
    "first8Mask": "true",
    "maskQr": "true",
}

# Function to process each image
def process_image(file_path):
    with open(file_path, "rb") as f:
        files = {"file": f}
        response = requests.post(API_URL, headers=HEADERS, files=files)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Error processing {file_path}: {response.text}")
            return None

# Main script
def main():
    data_rows = []  # To store rows for the CSV

    for file_name in os.listdir(IMAGE_DIR):
        file_path = os.path.join(IMAGE_DIR, file_name)
        if not os.path.isfile(file_path):
            continue  # Skip directories or invalid files

        print(f"Processing {file_name}...")
        response_data = process_image(file_path)

        if response_data:
            # Save masked image if present
            masked_image_base64 = response_data.get("maskedImage", "")
            if masked_image_base64:
                masked_image_path = os.path.join(MASKED_IMAGE_DIR, f"masked_{file_name}")
                with open(masked_image_path, "wb") as img_file:
                    img_file.write(base64.b64decode(masked_image_base64))

            # Prepare data for CSV
            data_rows.append({
                "Filename": file_name,
                "Aadhar Number": response_data.get("aadharNumber", ""),
                "Aadhar Detected": response_data.get("aadharNumberDetected", False),
                "Error": response_data.get("error", ""),
                "Masked Image Saved": bool(masked_image_base64),
                "No. of Aadhar Detected": response_data.get("noOfAadharDetected", 0),
                "No. of QR Codes Detected": response_data.get("noOfQrDetected", 0),
                "QR Code Detected": response_data.get("qrCodeDetected", False),
            })

    # Write data to CSV
    with open(CSV_OUTPUT, "w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=[
            "Filename", "Aadhar Number", "Aadhar Detected", "Error",
            "Masked Image Saved", "No. of Aadhar Detected", 
            "No. of QR Codes Detected", "QR Code Detected"
        ])
        writer.writeheader()
        writer.writerows(data_rows)

    print(f"Process completed. Results saved to {CSV_OUTPUT}")

# Run the script
if __name__ == "__main__":
    main()
