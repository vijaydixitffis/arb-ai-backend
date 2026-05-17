import { DomainAgent, Finding } from './domain-agent.ts'

export class BusinessDomainAgent extends DomainAgent {
  domain = 'business'
  relevantPrinciples = ['B-01', 'B-02', 'B-03', 'B-STD-01', 'B-STD-02']
  
  protected extractFindings(artifactText: string, mdContent: string): Finding[] {
    const findings: Finding[] = []
    const lowerText = artifactText.toLowerCase()
    
    // B-01: Business Requirements
    if (!lowerText.includes('business requirement') && !lowerText.includes('brd')) {
      findings.push({
        domain: this.domain,
        principle_id: 'B-01',
        severity: 'blocker',
        finding: 'No documented business requirements',
        recommendation: 'Create and reference Business Requirements Document (BRD)'
      })
    }
    
    // B-02: Stakeholder Analysis
    if (!lowerText.includes('stakeholder') && !lowerText.includes('business owner')) {
      findings.push({
        domain: this.domain,
        principle_id: 'B-02',
        severity: 'high',
        finding: 'No stakeholder analysis documented',
        recommendation: 'Identify and document all stakeholders, business owners, and their roles'
      })
    }
    
    // B-03: Business Continuity
    if (!lowerText.includes('continuity') && !lowerText.includes('disaster recovery')) {
      findings.push({
        domain: this.domain,
        principle_id: 'B-03',
        severity: 'high',
        finding: 'No business continuity plan documented',
        recommendation: 'Document business continuity and disaster recovery requirements'
      })
    }
    
    return findings
  }
}
