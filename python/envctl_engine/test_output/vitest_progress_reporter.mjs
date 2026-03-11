function writeMarker(text) {
  process.stdout.write(`${text}\n`)
}

function countModuleTests(testModule) {
  if (!testModule?.children?.allTests) {
    return 0
  }
  return Array.from(testModule.children.allTests()).length
}

function moduleKey(testModule) {
  return String(
    testModule?.moduleId
      ?? testModule?.id
      ?? testModule?.name
      ?? Math.random().toString(36).slice(2),
  )
}

export default class EnvctlVitestProgressReporter {
  constructor() {
    this.expectedModules = 0
    this.collectedModuleTotals = new Map()
    this.discoveredTotal = 0
    this.current = 0
    this.total = 0
    this.totalLocked = false
  }

  onTestRunStart(specifications) {
    this.expectedModules = specifications.length
    this.collectedModuleTotals.clear()
    this.discoveredTotal = 0
    this.current = 0
    this.total = 0
    this.totalLocked = false
  }

  onTestModuleCollected(testModule) {
    const discovered = countModuleTests(testModule)
    if (discovered <= 0) {
      return
    }
    this.collectedModuleTotals.set(moduleKey(testModule), discovered)
    const runningTotal = Array.from(this.collectedModuleTotals.values()).reduce((acc, value) => acc + value, 0)
    if (runningTotal > this.discoveredTotal) {
      this.discoveredTotal = runningTotal
      writeMarker(`ENVCTL_TEST_DISCOVERED:${this.discoveredTotal}`)
    }
    if (!this.totalLocked && this.expectedModules > 0 && this.collectedModuleTotals.size >= this.expectedModules) {
      this.total = this.discoveredTotal
      this.totalLocked = this.total > 0
      if (this.totalLocked) {
        writeMarker(`ENVCTL_TEST_TOTAL:${this.total}`)
      }
    }
  }

  onTestCaseResult() {
    this.current += 1
    if (this.totalLocked && this.total > 0) {
      writeMarker(`ENVCTL_TEST_PROGRESS:${this.current}/${this.total}`)
      return
    }
    writeMarker(`ENVCTL_TEST_COMPLETE:${this.current}`)
  }
}
