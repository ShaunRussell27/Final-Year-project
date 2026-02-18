import Foundation
import HealthKit

struct DailySummaryPayload: Codable {
	let userId: String
	let date: String
	let collectedAt: String
	let steps: Int?
	let sleepMinutes: Int?
	let restingHr: Double?
	let avgHr: Double?
	let hrSamplesCount: Int?

	enum CodingKeys: String, CodingKey {
		case userId = "user_id"
		case date
		case collectedAt = "collected_at"
		case steps
		case sleepMinutes = "sleep_minutes"
		case restingHr = "resting_hr"
		case avgHr = "avg_hr"
		case hrSamplesCount = "hr_samples_count"
	}
}

@MainActor
final class HealthKitManager: ObservableObject {
	private let healthStore = HKHealthStore()

	func requestPermissions() async throws {
		guard HKHealthStore.isHealthDataAvailable() else {
			throw NSError(domain: "HealthKitManager", code: 1, userInfo: [NSLocalizedDescriptionKey: "Health data is not available on this device."])
		}

		var readTypes: Set<HKObjectType> = []
		if let stepsType = HKObjectType.quantityType(forIdentifier: .stepCount) {
			readTypes.insert(stepsType)
		}
		if let sleepType = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) {
			readTypes.insert(sleepType)
		}
		if let restingHrType = HKObjectType.quantityType(forIdentifier: .restingHeartRate) {
			readTypes.insert(restingHrType)
		}

		try await withCheckedThrowingContinuation { continuation in
			healthStore.requestAuthorization(toShare: nil, read: readTypes) { success, error in
				if let error {
					continuation.resume(throwing: error)
					return
				}
				if success {
					continuation.resume()
				} else {
					continuation.resume(throwing: NSError(domain: "HealthKitManager", code: 2, userInfo: [NSLocalizedDescriptionKey: "Health permission request was not granted."]))
				}
			}
		}
	}

	func fetchTodaySummary(userId: String) async throws -> DailySummaryPayload {
		let now = Date()
		let calendar = Calendar.current
		let startOfToday = calendar.startOfDay(for: now)
		let dateString = Self.dayFormatter.string(from: startOfToday)
		let collectedAt = Self.isoFormatter.string(from: now)

		async let steps = fetchTodaySteps(from: startOfToday, to: now)
		async let sleepMinutes = fetchLastNightSleepMinutes(referenceDate: now)
		async let restingHr = fetchTodayRestingHR(from: startOfToday, to: now)

		return DailySummaryPayload(
			userId: userId,
			date: dateString,
			collectedAt: collectedAt,
			steps: try await steps,
			sleepMinutes: try await sleepMinutes,
			restingHr: try await restingHr,
			avgHr: nil,
			hrSamplesCount: nil
		)
	}

	func uploadTodaySummary(baseURL: String, userId: String) async throws {
		let payload = try await fetchTodaySummary(userId: userId)
		let endpoint = baseURL.trimmingCharacters(in: CharacterSet(charactersIn: "/")) + "/ingest/healthkit"

		guard let url = URL(string: endpoint) else {
			throw NSError(domain: "HealthKitManager", code: 3, userInfo: [NSLocalizedDescriptionKey: "Invalid backend URL"])
		}

		var request = URLRequest(url: url)
		request.httpMethod = "POST"
		request.setValue("application/json", forHTTPHeaderField: "Content-Type")
		request.httpBody = try JSONEncoder().encode(payload)

		let (_, response) = try await URLSession.shared.data(for: request)
		guard let httpResponse = response as? HTTPURLResponse else {
			throw NSError(domain: "HealthKitManager", code: 4, userInfo: [NSLocalizedDescriptionKey: "Invalid response from backend"])
		}

		guard (200...299).contains(httpResponse.statusCode) else {
			throw NSError(domain: "HealthKitManager", code: httpResponse.statusCode, userInfo: [NSLocalizedDescriptionKey: "Backend returned status \(httpResponse.statusCode)"])
		}
	}

	private func fetchTodaySteps(from startDate: Date, to endDate: Date) async throws -> Int? {
		guard let stepType = HKQuantityType.quantityType(forIdentifier: .stepCount) else {
			return nil
		}

		let predicate = HKQuery.predicateForSamples(withStart: startDate, end: endDate)

		return try await withCheckedThrowingContinuation { continuation in
			let query = HKStatisticsQuery(quantityType: stepType, quantitySamplePredicate: predicate, options: .cumulativeSum) { _, result, error in
				if let error {
					continuation.resume(throwing: error)
					return
				}
				let value = result?.sumQuantity()?.doubleValue(for: HKUnit.count())
				continuation.resume(returning: value.map { Int($0.rounded()) })
			}
			healthStore.execute(query)
		}
	}

	private func fetchLastNightSleepMinutes(referenceDate: Date) async throws -> Int? {
		guard let sleepType = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) else {
			return nil
		}

		let calendar = Calendar.current
		let noonToday = calendar.date(bySettingHour: 12, minute: 0, second: 0, of: referenceDate) ?? referenceDate
		let yesterdayEvening = calendar.date(byAdding: .hour, value: -18, to: noonToday) ?? referenceDate
		let predicate = HKQuery.predicateForSamples(withStart: yesterdayEvening, end: noonToday)
		let sortDescriptor = NSSortDescriptor(key: HKSampleSortIdentifierStartDate, ascending: true)

		return try await withCheckedThrowingContinuation { continuation in
			let query = HKSampleQuery(sampleType: sleepType, predicate: predicate, limit: HKObjectQueryNoLimit, sortDescriptors: [sortDescriptor]) { _, samples, error in
				if let error {
					continuation.resume(throwing: error)
					return
				}

				guard let categorySamples = samples as? [HKCategorySample], !categorySamples.isEmpty else {
					continuation.resume(returning: nil)
					return
				}

				var totalMinutes = 0
				for sample in categorySamples {
					if sample.value == HKCategoryValueSleepAnalysis.inBed.rawValue ||
						sample.value == HKCategoryValueSleepAnalysis.awake.rawValue {
						continue
					}

					let seconds = sample.endDate.timeIntervalSince(sample.startDate)
					totalMinutes += Int((seconds / 60.0).rounded())
				}

				continuation.resume(returning: totalMinutes > 0 ? totalMinutes : nil)
			}
			healthStore.execute(query)
		}
	}

	private func fetchTodayRestingHR(from startDate: Date, to endDate: Date) async throws -> Double? {
		guard let restingType = HKQuantityType.quantityType(forIdentifier: .restingHeartRate) else {
			return nil
		}

		let predicate = HKQuery.predicateForSamples(withStart: startDate, end: endDate)
		let unit = HKUnit.count().unitDivided(by: .minute())

		return try await withCheckedThrowingContinuation { continuation in
			let query = HKStatisticsQuery(quantityType: restingType, quantitySamplePredicate: predicate, options: .discreteAverage) { _, result, error in
				if let error {
					continuation.resume(throwing: error)
					return
				}
				let bpm = result?.averageQuantity()?.doubleValue(for: unit)
				continuation.resume(returning: bpm)
			}
			healthStore.execute(query)
		}
	}

	private static let dayFormatter: DateFormatter = {
		let formatter = DateFormatter()
		formatter.dateFormat = "yyyy-MM-dd"
		formatter.locale = Locale(identifier: "en_US_POSIX")
		return formatter
	}()

	private static let isoFormatter: ISO8601DateFormatter = {
		let formatter = ISO8601DateFormatter()
		formatter.formatOptions = [.withInternetDateTime]
		return formatter
	}()
}
