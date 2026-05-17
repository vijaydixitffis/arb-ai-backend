import { DomainAgent, Finding } from './domain-agent.ts'

export class SolutionDomainAgent extends DomainAgent {
  domain = 'solution'
  relevantPrinciples = ['G-01', 'G-02', 'G-03', 'G-04', 'G-05']
  
  protected extractFindings(artifactText: string, mdContent: string): Finding[] {
    const findings: Finding[] = []
    const lowerText = artifactText.toLowerCase()
    
    // G-01: Focus On Customer
    if (!lowerText.includes('customer') && !lowerText.includes('user experience')) {
      findings.push({
        domain: this.domain,
        principle_id: 'G-01',
        severity: 'high',
        finding: 'No explicit customer focus or user experience considerations documented',
        recommendation: 'Add customer problem statement, success metrics, and UX considerations'
      })
    }
    
    // G-02: Bias For Action
    if (!lowerText.includes('phased') && !lowerText.includes('incremental')) {
      findings.push({
        domain: this.domain,
        principle_id: 'G-02',
        severity: 'medium',
        finding: 'No phased delivery approach documented',
        recommendation: 'Document phased delivery plan with intermediate milestones'
      })
    }
    
    // G-03: Think Globally, Act Locally
    if (!lowerText.includes('enterprise') && !lowerText.includes('integration')) {
      findings.push({
        domain: this.domain,
        principle_id: 'G-03',
        severity: 'high',
        finding: 'No consideration of enterprise architecture landscape',
        recommendation: 'Review against enterprise capability map and integration catalogue'
      })
    }
    
    // G-04: Design For Reliability
    if (!lowerText.includes('availability') && !lowerText.includes('ha') && !lowerText.includes('dr')) {
      findings.push({
        domain: this.domain,
        principle_id: 'G-04',
        severity: 'blocker',
        finding: 'No reliability targets (HA/DR) defined',
        recommendation: 'Define HA targets, RPO/RTO objectives, and failure mode analysis'
      })
    }
    
    return findings
  }
}
