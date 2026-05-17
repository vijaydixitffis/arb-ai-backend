import { DomainAgent, Finding } from './domain-agent.ts'

export class NFRAgent extends DomainAgent {
  domain = 'nfr'
  relevantPrinciples = ['NFR-01', 'NFR-02', 'NFR-03', 'NFR-04']
  
  protected extractFindings(artifactText: string, mdContent: string): Finding[] {
    const findings: Finding[] = []
    const lowerText = artifactText.toLowerCase()
    
    // NFR-01: Performance
    if (!lowerText.includes('performance') && !lowerText.includes('latency') && !lowerText.includes('throughput')) {
      findings.push({
        domain: this.domain,
        principle_id: 'NFR-01',
        severity: 'high',
        finding: 'No performance requirements documented',
        recommendation: 'Define performance targets (latency, throughput, response time)'
      })
    }
    
    // NFR-02: Availability
    if (!lowerText.includes('availability') && !lowerText.includes('sla') && !lowerText.includes('uptime')) {
      findings.push({
        domain: this.domain,
        principle_id: 'NFR-02',
        severity: 'blocker',
        finding: 'No availability targets documented',
        recommendation: 'Define availability SLA (e.g., 99.9%, 99.99%) and failover mechanisms'
      })
    }
    
    // NFR-03: Scalability
    if (!lowerText.includes('scalability') && !lowerText.includes('scale') && !lowerText.includes('elastic')) {
      findings.push({
        domain: this.domain,
        principle_id: 'NFR-03',
        severity: 'high',
        finding: 'No scalability requirements documented',
        recommendation: 'Define horizontal and vertical scaling strategies'
      })
    }
    
    // NFR-04: Disaster Recovery
    if (!lowerText.includes('disaster recovery') && !lowerText.includes('rpo') && !lowerText.includes('rto')) {
      findings.push({
        domain: this.domain,
        principle_id: 'NFR-04',
        severity: 'blocker',
        finding: 'No disaster recovery objectives documented',
        recommendation: 'Define RPO, RTO, and disaster recovery testing procedures'
      })
    }
    
    return findings
  }
}
