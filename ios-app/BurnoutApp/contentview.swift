import SwiftUI

struct ContentView: View {
	@StateObject private var healthKitManager = HealthKitManager()

	@State private var statusMessage = "Ready"
	@State private var isLoading = false

	// Replace with your Railway URL for device testing, e.g. https://your-app.up.railway.app
	private let backendBaseURL = "http://127.0.0.1:8000"
	private let userId = UIDevice.current.identifierForVendor?.uuidString ?? "ios-user"

	var body: some View {
		VStack(spacing: 16) {
			Text("Burnout MVP")
				.font(.title2)
				.bold()

			Button(action: requestPermissions) {
				Text("Request Health Permissions")
					.frame(maxWidth: .infinity)
			}
			.buttonStyle(.borderedProminent)
			.disabled(isLoading)

			Button(action: uploadTodaySummary) {
				Text("Upload Today Summary")
					.frame(maxWidth: .infinity)
			}
			.buttonStyle(.bordered)
			.disabled(isLoading)

			if isLoading {
				ProgressView()
			}

			Text(statusMessage)
				.font(.footnote)
				.foregroundStyle(.secondary)
				.multilineTextAlignment(.center)

			Spacer()
		}
		.padding()
	}

	private func requestPermissions() {
		isLoading = true
		statusMessage = "Requesting Health permissions..."

		Task {
			do {
				try await healthKitManager.requestPermissions()
				statusMessage = "Health permissions granted."
			} catch {
				statusMessage = "Permissions failed: \(error.localizedDescription)"
			}
			isLoading = false
		}
	}

	private func uploadTodaySummary() {
		isLoading = true
		statusMessage = "Collecting and uploading summary..."

		Task {
			do {
				try await healthKitManager.uploadTodaySummary(baseURL: backendBaseURL, userId: userId)
				statusMessage = "Upload succeeded for user \(userId)."
			} catch {
				statusMessage = "Upload failed: \(error.localizedDescription)"
			}
			isLoading = false
		}
	}
}

#Preview {
	ContentView()
}
