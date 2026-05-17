import { DomainAgent, Finding } from './domain-agent.ts'

export class DataDomainAgent extends DomainAgent {
  domain = 'data'
  relevantPrinciples = ['D-01', 'D-02', 'D-03', 'D-STD-01']
  
  protected extractFindings(artifactText: string, mdContent: string): Finding[] {
    const findings: Finding[] = []
    const lowerText = artifactText.toLowerCase()
    
    // D-01: Data Classification
    if (!lowerText.includes('data classification') && !lowerText.includes('sensitive')) {
      findings.push({
        domain: this.domain,
        principle_id: 'D-01',
        severity: 'blocker',
        finding: 'No data classification documented',
        recommendation: 'Classify all data according to sensitivity and define handling requirements'
      })
    }
    
    // D-02: Data Architecture
    if (!lowerText.includes('data model') && !lowerText.includes('schema') && !lowerText.includes('entity')) {
      findings.push({
        domain: this.domain,
        principle_id: 'D-02',
        severity: 'high',
        finding: 'No data architecture or data model documented',
        recommendation: 'Provide data architecture diagram and entity-relationship models'
      })
    }
    
    // D-03: Data Governance
    if (!lowerText.includes('data governance') && !lowerText.includes('data owner')) {
      findings.push({
        domain: this.domain,
        principle_id: 'D-03',
        severity: 'high',
        finding: 'No data governance framework documented',
        recommendation: 'Define data ownership, stewardship, and governance policies'
      })
    }
    
    return findings
  }
}
