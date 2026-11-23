document.addEventListener('DOMContentLoaded', function () {
    const startBtn = document.getElementById('start-scan-btn');
    const stopBtn = document.getElementById('stop-scan-btn');
    const resultContainer = document.getElementById('qr-reader-results');
    const readerElement = document.getElementById('qr-reader');

    if (!readerElement || !startBtn || !stopBtn) {
        return;
    }


    let html5QrcodeScanner;

    // --- 1. Define the Callback Functions ---

    function onScanSuccess(decodedText, decodedResult) {
        // Only proceed if our scanner instance is active.
        if (html5QrcodeScanner) {
            html5QrcodeScanner.clear().then(() => {
                console.log("Scanner cleared after success.");
                
                resultContainer.innerHTML = `<div class="alert alert-success"><strong>Scan Successful!</strong> Redirecting...</div>`;
                startBtn.disabled = true;
                stopBtn.disabled = true;
                
                window.location.href = `${ISI_SCANNER_CONFIG.lookupUrl}?code=${encodeURIComponent(decodedText)}`;
            }).catch(error => {
                console.error("Failed to clear scanner after success:", error);
                window.location.href = `${ISI_SCANNER_CONFIG.lookupUrl}?code=${encodeURIComponent(decodedText)}`;
            });
        }
    }

    function onScanFailure(error) {
        // Ignore "QR code not found" errors
        if (/QR code not found/.test(error)) {
            return;
        }
        console.warn(`QR Code scan error: ${error}`);
        resultContainer.innerHTML = `<div class="alert alert-warning">${error}</div>`;
    }

    // --- 2. Set up Event Listeners for the Buttons ---

    startBtn.addEventListener('click', () => {
        resultContainer.innerHTML = '';
        readerElement.style.display = 'block';

        html5QrcodeScanner = new Html5QrcodeScanner(
            "qr-reader", 
            { 
                fps: 10,
                qrbox: { width: 250, height: 250 },
                rememberLastUsedCamera: true,
                supportedScanTypes: [
                    Html5QrcodeScanType.SCAN_TYPE_CAMERA,
                    Html5QrcodeScanType.SCAN_TYPE_FILE
                ]
            },
            false // verbose = false
        );

        html5QrcodeScanner.render(onScanSuccess, onScanFailure);

        startBtn.style.display = 'none';
        stopBtn.style.display = 'inline-block';
    });

    stopBtn.addEventListener('click', () => {
        // Check if the scanner object exists before trying to stop it.
        if (html5QrcodeScanner) {
            html5QrcodeScanner.clear().then(() => {
                console.log("Scanner cleared by user.");
                resultContainer.innerHTML = '<div class="alert alert-info">Scanning stopped.</div>';
                
                startBtn.style.display = 'inline-block';
                stopBtn.style.display = 'none';
            }).catch(error => {
                console.error("Failed to clear scanner:", error);
                // Force UI update even if clearing fails.
                startBtn.style.display = 'inline-block';
                stopBtn.style.display = 'none';
            });
        }
    });
});