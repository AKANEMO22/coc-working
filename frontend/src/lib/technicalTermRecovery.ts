/**
 * CÓC ĐI LÀM — Technical-Term Recovery (§5)
 * Bộ phục hồi thuật ngữ kỹ thuật tiếng Anh khi ứng viên nói code-switching (Việt - Anh).
 * Dictionary matches are suggestions only, not acoustic evidence or
 * calibrated confidence. Qwen's original words must remain untouched.
 */

export interface TermCandidate {
  raw: string;
  recovered: string;
  domain: string;
  source: "phonetic_lexicon";
}

// Từ điển phát âm bồi / việt hóa sang chuẩn quốc tế
const PHONETIC_LEXICON: Record<string, { term: string; domain: string }> = {
  // Frontend
  "re ắc": { term: "React", domain: "frontend" },
  "ri ác": { term: "React", domain: "frontend" },
  "vui di ét": { term: "Vue.js", domain: "frontend" },
  "ăng gu la": { term: "Angular", domain: "frontend" },
  "tai xờ kíp": { term: "TypeScript", domain: "frontend" },
  "gia va xờ kíp": { term: "JavaScript", domain: "frontend" },
  "teo guyn": { term: "Tailwind CSS", domain: "frontend" },
  "nếch di ét": { term: "Next.js", domain: "frontend" },

  // Backend & Databases
  "nốt di ét": { term: "Node.js", domain: "backend" },
  "nốt dét": { term: "Node.js", domain: "backend" },
  "xờ pring bút": { term: "Spring Boot", domain: "backend" },
  "gian gô": { term: "Django", domain: "backend" },
  "phát ê pi ai": { term: "FastAPI", domain: "backend" },
  "mông gồ": { term: "MongoDB", domain: "database" },
  "mông go đi bi": { term: "MongoDB", domain: "database" },
  "rét đít": { term: "Redis", domain: "database" },
  "pốt gờ rét": { term: "PostgreSQL", domain: "database" },
  "ét kiu eo": { term: "SQL", domain: "database" },
  "nô ét kiu eo": { term: "NoSQL", domain: "database" },
  "ai xi đi": { term: "ACID", domain: "database" },

  // DevOps & Cloud
  "đốc cơ": { term: "Docker", domain: "devops" },
  "cu bơ nét tít": { term: "Kubernetes", domain: "devops" },
  "cúp bê nê tít": { term: "Kubernetes", domain: "devops" },
  "kây tám ét": { term: "K8s", domain: "devops" },
  "xi ai xi đi": { term: "CI/CD", domain: "devops" },
  "a vê kép": { term: "AWS", domain: "cloud" },
  "ây đắp bờ liu ét": { term: "AWS", domain: "cloud" },
  "di xi pi": { term: "GCP", domain: "cloud" },

  // Architecture & Protocols
  "rét phân": { term: "RESTful", domain: "architecture" },
  "rét ê pi ai": { term: "REST API", domain: "architecture" },
  "gờ ráp kiu eo": { term: "GraphQL", domain: "architecture" },
  "o ót hai": { term: "OAuth 2.0", domain: "security" },
  "míc rô sơ vít": { term: "Microservices", domain: "architecture" },
  "kháp ca": { term: "Kafka", domain: "architecture" },
  "quép sốc két": { term: "WebSocket", domain: "protocol" },

  // Git & Workflow
  "gít": { term: "Git", domain: "workflow" },
  "gít hắp": { term: "GitHub", domain: "workflow" },
  "cô mít": { term: "commit", domain: "workflow" },
  "pút": { term: "push", domain: "workflow" },
  "mớt": { term: "merge", domain: "workflow" },
  "bấc": { term: "bug", domain: "workflow" },
  "pê rờ": { term: "PR", domain: "workflow" },
};

/**
 * Tính khoảng cách Levenshtein giữa 2 chuỗi
 */
function levenshteinDistance(a: string, b: string): number {
  const matrix: number[][] = [];
  for (let i = 0; i <= b.length; i++) {
    matrix[i] = [i];
  }
  for (let j = 0; j <= a.length; j++) {
    matrix[0][j] = j;
  }
  for (let i = 1; i <= b.length; i++) {
    for (let j = 1; j <= a.length; j++) {
      if (b.charAt(i - 1) === a.charAt(j - 1)) {
        matrix[i][j] = matrix[i - 1][j - 1];
      } else {
        matrix[i][j] = Math.min(
          matrix[i - 1][j - 1] + 1, // substitution
          matrix[i][j - 1] + 1,     // insertion
          matrix[i - 1][j] + 1      // deletion
        );
      }
    }
  }
  return matrix[b.length][a.length];
}

export class TechnicalTermRecovery {
  /**
   * Phục hồi thuật ngữ tiếng Anh từ văn bản tiếng Việt phát âm bồi
   */
  recover(rawTranscript: string): {
    recoveredText: string;
    candidates: TermCandidate[];
  } {
    const candidates: TermCandidate[] = [];

    // Duyệt qua các từ điển âm vị
    for (const [phonetic, meta] of Object.entries(PHONETIC_LEXICON)) {
      const escaped = phonetic.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const regex = new RegExp(`(?<![\\p{L}\\p{N}])${escaped}(?![\\p{L}\\p{N}])`, "giu");
      if (regex.test(rawTranscript)) {
        candidates.push({
          raw: phonetic,
          recovered: meta.term,
          domain: meta.domain,
          source: "phonetic_lexicon",
        });
      }
    }

    return {
      recoveredText: rawTranscript,
      candidates,
    };
  }
}

export const technicalTermRecovery = new TechnicalTermRecovery();
