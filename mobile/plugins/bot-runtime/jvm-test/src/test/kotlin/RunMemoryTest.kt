import com.barantheviber.tradingbot.RunMemory
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class RunMemoryTest {
  private class MapStore : RunMemory.Store {
    val values = mutableMapOf<String, Any?>()
    override fun getBoolean(key: String) = values[key] as? Boolean ?: false
    override fun getString(key: String) = values[key] as? String
    override fun put(values: Map<String, Any?>) {
      this.values.putAll(values)
    }
  }

  private fun memory() = RunMemory(MapStore())

  @Test
  fun `a bot running when the phone went down comes back`() {
    val m = memory()
    m.started("cfg")
    assertEquals("cfg", m.configToResume())
    assertEquals("cfg", m.configForStart(null))
  }

  @Test
  fun `a bot the user stopped stays stopped after a restart`() {
    val m = memory()
    m.started("cfg")
    m.stoppedByUser()
    assertNull(m.configToResume())
    assertNull(m.configForStart(null))
  }

  @Test
  fun `a bot that ended by itself stays stopped`() {
    val m = memory()
    m.started("cfg")
    m.ended()
    assertNull(m.configToResume())
  }

  @Test
  fun `a fresh install never starts by itself`() {
    assertNull(memory().configToResume())
  }

  @Test
  fun `the user can start again after stopping, with the new setup`() {
    val m = memory()
    m.started("old")
    m.stoppedByUser()
    assertEquals("new", m.configForStart("new"))
    m.started("new")
    assertEquals("new", m.configToResume())
  }
}
