export interface Finding {
  domain: string
  principle_id: string
  finding_id?: string
  severity: 'BLOCKER' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO' | 'critical' | 'major' | 'minor'
  finding: string
  recommendation: string
  check_category?: string
  // extended fields (migration 022)
  title?: string | null
  rag_score?: number
  evidence_source?: string | null
  standard_violated?: string | null
  impact?: string | null
  is_blocker?: boolean
  links_to_action_ids?: string[]
  links_to_adr_id?: string | null
  waiver_eligible?: boolean
  kb_reference?: string[]
  artifact_ref?: string | null
  kb_ref?: string | null
}

export interface DomainResult {
  domain: string
  score: number   // rag_score 1–5 (authoritative from LLM summary.rag_score)
  findings: Finding[]
}

export abstract class DomainAgent {
  abstract domain: string
  abstract relevantPrinciples: string[]

  validate(artifactText: string, mdContent: string): DomainResult {
    const relevantMD = this.extractRelevantMD(mdContent)
    const findings   = this.extractFindings(artifactText, relevantMD)
    const score      = this.calculateScore(findings)
    return { domain: this.domain, score, findings }
  }

  protected extractRelevantMD(mdContent: string): string {
    const lines: string[] = []
    let inRelevantSection = false
    for (const line of mdContent.split('\n')) {
      if (this.relevantPrinciples.some(p => line.includes(p))) inRelevantSection = true
      if (inRelevantSection) {
        lines.push(line)
        if (line.startsWith('## ') && !this.relevantPrinciples.some(p => line.includes(p))) {
          inRelevantSection = false
        }
      }
    }
    return lines.join('\n')
  }

  protected abstract extractFindings(artifactText: string, mdContent: string): Finding[]

  protected calculateScore(findings: Finding[]): number {
    if (findings.length === 0) return 5
    if (findings.some(f => f.severity === 'critical')) return 1
    const majorCount = findings.filter(f => f.severity === 'major').length
    if (majorCount >= 3) return 2
    if (majorCount >= 1) return 3
    return 4
  }
}
