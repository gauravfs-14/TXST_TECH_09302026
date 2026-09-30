import { Page } from '../components/Chrome'
import { HomeHero } from '../sections/HomeHero'
import { HowItWorks } from '../sections/HowItWorks'
import { Video } from '../sections/Video'

export default function Home() {
  return (
    <Page overlayNav>
      <HomeHero />
      <HowItWorks />
      <Video />
    </Page>
  )
}
